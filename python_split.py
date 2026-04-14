
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
            "No DICOM file found. Place the Enhanced MR file next to the script "
            "or pass it as a command-line argument."
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


def _first_str(value, default=None):
    if value is None:
        return default
    if isinstance(value, (list, tuple)):
        if not value:
            return default
        return str(value[0])
    return str(value)


def _nth_str(value, idx, default=None):
    if value is None:
        return default
    if isinstance(value, (list, tuple)):
        if len(value) > idx:
            return str(value[idx])
        return default
    if idx == 0:
        return str(value)
    return default


def synthesize_mr_legacy_attributes(ds: Dataset) -> None:
    eff_te = getattr(ds, "EffectiveEchoTime", None)
    try:
        eff_te_num = float(eff_te) if eff_te is not None and str(eff_te) != "" else 0.0
    except Exception:
        eff_te_num = 0.0

    ds.EchoTime = "" if eff_te_num == 0.0 else eff_te_num

    scanning_sequence = []
    eps = _first_str(getattr(ds, "EchoPulseSequence", None))

    if eps != "GRADIENT":
        scanning_sequence.append("SE")
    if eps != "SPIN":
        scanning_sequence.append("GR")
    if _first_str(getattr(ds, "InversionRecovery", None)) == "YES":
        scanning_sequence.append("IR")
    if _first_str(getattr(ds, "EchoPlanarPulseSequence", None)) == "YES":
        scanning_sequence.append("EP")

    if not scanning_sequence:
        scanning_sequence = ["SE"]
    ds.ScanningSequence = scanning_sequence

    sequence_variant = []

    if _first_str(getattr(ds, "SegmentedKSpaceTraversal", None)) != "SINGLE":
        sequence_variant.append("SK")

    mt = _first_str(getattr(ds, "MagnetizationTransfer", None))
    if mt is not None and mt != "NONE":
        sequence_variant.append("MTC")

    ssps = _first_str(getattr(ds, "SteadyStatePulseSequence", None))
    if ssps is not None and ssps != "NONE":
        sequence_variant.append("TRSS" if ssps == "TIME_REVERSED" else "SS")

    sp = _first_str(getattr(ds, "Spoiling", None))
    if sp is not None and sp != "NONE":
        sequence_variant.append("SP")

    op = _first_str(getattr(ds, "OversamplingPhase", None))
    if op is not None and op != "NONE":
        sequence_variant.append("OSP")

    if not sequence_variant:
        sequence_variant = ["NONE"]
    ds.SequenceVariant = sequence_variant

    scan_options = []

    per = _first_str(getattr(ds, "RectilinearPhaseEncodeReordering", None))
    if per is not None and per != "LINEAR":
        scan_options.append("PER")

    frame_type3 = _nth_str(getattr(ds, "ImageType", None), 2, "")
    if frame_type3 == "ANGIO":
        ds.AngioFlag = "Y"
    if frame_type3.startswith("CARD"):
        scan_options.append("CG")
    if frame_type3.endswith("RESP_GATED"):
        scan_options.append("RG")

    pfd = _first_str(getattr(ds, "PartialFourierDirection", None))
    if pfd == "PHASE":
        scan_options.append("PFP")
    elif pfd == "FREQUENCY":
        scan_options.append("PFF")

    spatial_presat = _first_str(getattr(ds, "SpatialPresaturation", None))
    if spatial_presat is not None and spatial_presat != "NONE":
        scan_options.append("SP")

    sss = _first_str(getattr(ds, "SpectrallySelectedSuppression", None))
    if sss is not None and sss.startswith("FAT"):
        scan_options.append("FS")

    fc = _first_str(getattr(ds, "FlowCompensation", None))
    if fc is not None and fc != "NONE":
        scan_options.append("FC")

    ds.ScanOptions = scan_options if scan_options else ""


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
        raise ValueError(f"Unexpected frame dimensions: {frame.shape}")

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
            f"Frame {frame_no}: required geometry tags are missing after flattening "
            f"functional groups: {', '.join(missing)}"
        )


def validate_required_mr_tags(ds: Dataset, frame_no: int) -> None:
    missing = []

    if not hasattr(ds, "ScanningSequence") or not getattr(ds, "ScanningSequence"):
        missing.append("ScanningSequence (0018,0020)")
    if not hasattr(ds, "SequenceVariant") or not getattr(ds, "SequenceVariant"):
        missing.append("SequenceVariant (0018,0021)")
    if not hasattr(ds, "ScanOptions"):
        missing.append("ScanOptions (0018,0022)")
    if not hasattr(ds, "EchoTime"):
        missing.append("EchoTime (0018,0081)")

    if missing:
        raise ValueError(
            f"Frame {frame_no}: required MR legacy tags are missing: {', '.join(missing)}"
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
        raise ValueError("The file is not multiframe or contains only 1 frame.")

    print(f"Input:  {input_path.name}")
    print(f"Frames: {n_frames}")
    print(f"Output: {out_dir}")

    all_frames = ds.pixel_array
    new_series_uid = generate_uid()

    shared_fgs = None
    if hasattr(ds, "SharedFunctionalGroupsSequence") and ds.SharedFunctionalGroupsSequence:
        shared_fgs = ds.SharedFunctionalGroupsSequence[0]

    if not hasattr(ds, "PerFrameFunctionalGroupsSequence") or not ds.PerFrameFunctionalGroupsSequence:
        raise ValueError("PerFrameFunctionalGroupsSequence is missing or empty.")

    for i in range(n_frames):
        frame_no = i + 1
        frame = np.ascontiguousarray(all_frames[i])

        out = build_base_dataset(ds)
        ensure_file_meta(out)

        per_frame_fgs = ds.PerFrameFunctionalGroupsSequence[i]

        flatten_functional_groups(out, shared_fgs)
        flatten_functional_groups(out, per_frame_fgs)

        convert_frame_type_to_image_type(out)
        synthesize_mr_legacy_attributes(out)

        new_sop_uid = generate_uid()
        out.SOPClassUID = MRImageStorage
        out.SOPInstanceUID = new_sop_uid
        out.SeriesInstanceUID = new_series_uid
        out.InstanceNumber = frame_no

        if hasattr(out, "SeriesDescription") and out.SeriesDescription:
            out.SeriesDescription = f"{out.SeriesDescription} [split]"
        else:
            out.SeriesDescription = "Split Enhanced MR"

        set_required_pixel_tags_from_array(out, frame)
        validate_required_geometry(out, frame_no)
        validate_required_mr_tags(out, frame_no)

        out.is_little_endian = True
        out.is_implicit_VR = False

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

        print(f"  written: {outfile.name}")

    print("Done.")


if __name__ == "__main__":
    main()
