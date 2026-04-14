from __future__ import annotations

import sys
from copy import deepcopy
from pathlib import Path

import numpy as np
from pydicom import dcmread
from pydicom.dataset import Dataset, FileMetaDataset
from pydicom.filewriter import dcmwrite
from pydicom.uid import (
    ExplicitVRLittleEndian,
    MRImageStorage,
    PYDICOM_IMPLEMENTATION_UID,
    generate_uid,
)


EXCLUDE_KEYWORDS = {
    "ReferencedImageEvidenceSequence",
    "SourceImageEvidenceSequence",
    "DimensionIndexSequence",
    "NumberOfFrames",
    "SharedFunctionalGroupsSequence",
    "PerFrameFunctionalGroupsSequence",
    "PixelData",
    "FloatPixelData",
    "DoubleFloatPixelData",
}


def ensure_file_meta(ds: Dataset) -> None:
    if not hasattr(ds, "file_meta") or ds.file_meta is None:
        ds.file_meta = FileMetaDataset()


def find_input_file(script_dir: Path) -> Path:
    preferred = [
        script_dir / "enhancedmr.dcm",
        script_dir / "EnhancedMR.dcm",
        script_dir / "enhanced_mr.dcm",
        script_dir / "multi.dcm",
    ]
    for path in preferred:
        if path.exists():
            return path

    candidates = sorted(
        p for p in script_dir.iterdir()
        if p.is_file() and p.suffix.lower() in {".dcm", ".ima"}
    )
    if not candidates:
        raise FileNotFoundError(
            "Keine DICOM-Datei gefunden. "
            "Lege die Enhanced-MR-Datei neben das Skript oder übergib sie als Argument."
        )
    return candidates[0]


def build_base_dataset(src: Dataset) -> Dataset:
    out = Dataset()
    for elem in src:
        if elem.keyword in EXCLUDE_KEYWORDS:
            continue
        out.add(deepcopy(elem))
    return out


def add_dataset_elements(dest: Dataset, src: Dataset) -> None:
    for elem in src:
        dest[elem.tag] = deepcopy(elem)


def flatten_functional_groups(dest: Dataset, fg_container: Dataset | None) -> None:
    """
    Orientiert sich an dcm4che/emf2sf:
    - ReferencedImageSequence direkt übernehmen
    - alle übrigen Functional Group Sequence Items (erstes Item) abflachen
    """
    if fg_container is None:
        return

    for elem in fg_container:
        if elem.VR != "SQ":
            continue
        if not elem.value:
            continue
        first_item = elem.value[0]
        if not isinstance(first_item, Dataset):
            continue

        if elem.keyword == "ReferencedImageSequence":
            dest[elem.tag] = deepcopy(elem)
        else:
            add_dataset_elements(dest, first_item)


def convert_frame_type_to_image_type(ds: Dataset) -> None:
    if hasattr(ds, "FrameType"):
        try:
            ds.ImageType = list(ds.FrameType)
        except Exception:
            ds.ImageType = ds.FrameType
        del ds.FrameType


def ensure_even_length(data: bytes) -> bytes:
    return data if len(data) % 2 == 0 else data + b"\x00"


def set_required_pixel_tags_from_array(ds: Dataset, frame: np.ndarray) -> None:
    frame = np.ascontiguousarray(frame)

    if frame.ndim == 2:
        rows, cols = frame.shape
        samples_per_pixel = 1
    elif frame.ndim == 3:
        rows, cols, samples_per_pixel = frame.shape
    else:
        raise ValueError(f"Unerwartete Frame-Dimension: {frame.shape}")

    ds.Rows = int(rows)
    ds.Columns = int(cols)
    ds.SamplesPerPixel = int(getattr(ds, "SamplesPerPixel", samples_per_pixel))

    if ds.SamplesPerPixel > 1 and not hasattr(ds, "PlanarConfiguration"):
        ds.PlanarConfiguration = 0

    pixel_bytes = ensure_even_length(frame.tobytes())
    ds.PixelData = pixel_bytes

    bits_allocated = int(getattr(ds, "BitsAllocated", frame.dtype.itemsize * 8))
    ds["PixelData"].VR = "OB" if bits_allocated <= 8 else "OW"


def validate_required_geometry(ds: Dataset, frame_no: int) -> None:
    missing = []

    if not hasattr(ds, "PixelSpacing"):
        missing.append("PixelSpacing (0028,0030)")
    if not hasattr(ds, "ImagePositionPatient"):
        missing.append("ImagePositionPatient (0020,0032)")
    if not hasattr(ds, "ImageOrientationPatient"):
        missing.append("ImageOrientationPatient (0020,0037)")

    if missing:
        raise ValueError(
            f"Frame {frame_no}: erforderliche Geometrie-Tags fehlen nach dem Abflachen der Functional Groups: "
            + ", ".join(missing)
        )


def main():
    script_dir = Path(__file__).resolve().parent
    input_path = Path(sys.argv[1]) if len(sys.argv) > 1 else find_input_file(script_dir)
    input_path = input_path.resolve()

    out_dir = input_path.parent / f"{input_path.stem}_split"
    out_dir.mkdir(exist_ok=True)

    ds = dcmread(str(input_path), force=False)

    n_frames = int(getattr(ds, "NumberOfFrames", 1))
    if n_frames <= 1:
        raise ValueError("Die Datei ist nicht multiframe oder enthält nur 1 Frame.")

    print(f"Eingabe: {input_path.name}")
    print(f"Frames:  {n_frames}")
    print(f"Output:  {out_dir}")

    # Kompatibler Weg ohne pydicom.pixels.pixel_array
    all_frames = ds.pixel_array

    # Wie emf2sf standardmäßig: neue SeriesInstanceUID
    new_series_uid = generate_uid()

    shared_fgs = None
    if hasattr(ds, "SharedFunctionalGroupsSequence") and ds.SharedFunctionalGroupsSequence:
        shared_fgs = ds.SharedFunctionalGroupsSequence[0]

    if not hasattr(ds, "PerFrameFunctionalGroupsSequence") or not ds.PerFrameFunctionalGroupsSequence:
        raise ValueError("PerFrameFunctionalGroupsSequence fehlt oder ist leer.")

    for i in range(n_frames):
        frame_no = i + 1
        frame = np.ascontiguousarray(all_frames[i])

        out = build_base_dataset(ds)
        ensure_file_meta(out)

        per_frame_fgs = ds.PerFrameFunctionalGroupsSequence[i]

        # emuliert dcm4che: Shared zuerst, dann Per-Frame drüber
        flatten_functional_groups(out, shared_fgs)
        flatten_functional_groups(out, per_frame_fgs)

        # emuliert dcm4che: ImageType aus FrameType erzeugen
        convert_frame_type_to_image_type(out)

        # Auf klassisches Single-Frame MR umstellen
        new_sop_uid = generate_uid()
        out.SOPClassUID = MRImageStorage
        out.SOPInstanceUID = new_sop_uid
        out.SeriesInstanceUID = new_series_uid
        out.InstanceNumber = frame_no

        if hasattr(out, "SeriesDescription") and out.SeriesDescription:
            out.SeriesDescription = f"{out.SeriesDescription} [split]"
        else:
            out.SeriesDescription = "Split Enhanced MR"

        # Pixel-Daten + VR
        set_required_pixel_tags_from_array(out, frame)

        # Fail fast, falls die für den Import kritischen Tags noch fehlen
        validate_required_geometry(out, frame_no)

        # Schreibmodus
        out.is_little_endian = True
        out.is_implicit_VR = False

        # File Meta
        out.file_meta.TransferSyntaxUID = ExplicitVRLittleEndian
        out.file_meta.MediaStorageSOPClassUID = MRImageStorage
        out.file_meta.MediaStorageSOPInstanceUID = new_sop_uid
        out.file_meta.ImplementationClassUID = PYDICOM_IMPLEMENTATION_UID

        outfile = out_dir / f"IM_{frame_no:04d}.dcm"
        dcmwrite(
            str(outfile),
            out,
            enforce_file_format=True,
            implicit_vr=False,
            little_endian=True,
        )

        print(f"  geschrieben: {outfile.name}")

    print("Fertig.")


if __name__ == "__main__":
    main()