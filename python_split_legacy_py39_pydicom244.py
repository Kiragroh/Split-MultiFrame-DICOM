from __future__ import annotations

import sys
from copy import deepcopy
from pathlib import Path

import numpy as np
from pydicom import dcmread
from pydicom.dataset import Dataset, FileMetaDataset
from pydicom.filewriter import dcmwrite
from pydicom.uid import ExplicitVRLittleEndian, generate_uid

# Compatibility fallbacks for older pydicom versions
try:
    from pydicom.uid import MRImageStorage
except Exception:
    MRImageStorage = "1.2.840.10008.5.1.4.1.1.4"  # MR Image Storage

try:
    from pydicom.uid import PYDICOM_IMPLEMENTATION_UID
except Exception:
    PYDICOM_IMPLEMENTATION_UID = "1.2.826.0.1.3680043.8.498.1"


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


def ensure_file_meta(ds):
    if not hasattr(ds, "file_meta") or ds.file_meta is None:
        ds.file_meta = FileMetaDataset()


def find_input_file(script_dir):
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


def build_base_dataset(src):
    out = Dataset()
    for elem in src:
        if elem.keyword in EXCLUDE_KEYWORDS:
            continue
        out.add(deepcopy(elem))
    return out


def add_dataset_elements(dest, src):
    for elem in src:
        dest[elem.tag] = deepcopy(elem)


def flatten_functional_groups(dest, fg_container):
    """
    Similar to dcm4che emf2sf:
    - keep ReferencedImageSequence as sequence
    - flatten the first item of all other functional group sequences
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


def convert_frame_type_to_image_type(ds):
    if hasattr(ds, "FrameType"):
        try:
            ds.ImageType = list(ds.FrameType)
        except Exception:
            ds.ImageType = ds.FrameType
        del ds.FrameType


def ensure_even_length(data):
    if len(data) % 2 == 0:
        return data
    return data + b"\x00"


def set_required_pixel_tags_from_array(ds, frame):
    frame = np.ascontiguousarray(frame)

    if frame.ndim == 2:
        rows, cols = frame.shape
        samples_per_pixel = 1
    elif frame.ndim == 3:
        rows, cols, samples_per_pixel = frame.shape
    else:
        raise ValueError("Unexpected frame dimensions: {0}".format(frame.shape))

    ds.Rows = int(rows)
    ds.Columns = int(cols)

    if not hasattr(ds, "SamplesPerPixel"):
        ds.SamplesPerPixel = int(samples_per_pixel)

    if int(ds.SamplesPerPixel) > 1 and not hasattr(ds, "PlanarConfiguration"):
        ds.PlanarConfiguration = 0

    pixel_bytes = ensure_even_length(frame.tobytes())
    ds.PixelData = pixel_bytes

    bits_allocated = int(getattr(ds, "BitsAllocated", frame.dtype.itemsize * 8))
    ds["PixelData"].VR = "OB" if bits_allocated <= 8 else "OW"


def validate_required_geometry(ds, frame_no):
    missing = []

    if not hasattr(ds, "PixelSpacing"):
        missing.append("PixelSpacing (0028,0030)")
    if not hasattr(ds, "ImagePositionPatient"):
        missing.append("ImagePositionPatient (0020,0032)")
    if not hasattr(ds, "ImageOrientationPatient"):
        missing.append("ImageOrientationPatient (0020,0037)")

    if missing:
        raise ValueError(
            "Frame {0}: required geometry tags are missing after flattening "
            "functional groups: {1}".format(frame_no, ", ".join(missing))
        )


def main():
    script_dir = Path(__file__).resolve().parent
    input_path = Path(sys.argv[1]) if len(sys.argv) > 1 else find_input_file(script_dir)
    input_path = input_path.resolve()

    out_dir = input_path.parent / "{0}_split".format(input_path.stem)
    out_dir.mkdir(exist_ok=True)

    ds = dcmread(str(input_path), force=False)

    n_frames = int(getattr(ds, "NumberOfFrames", 1))
    if n_frames <= 1:
        raise ValueError("The file is not multiframe or contains only 1 frame.")

    print("Input:  {0}".format(input_path.name))
    print("Frames: {0}".format(n_frames))
    print("Output: {0}".format(out_dir))

    # Compatible with pydicom 2.4.4
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

        # Shared first, then Per-Frame overwrites
        flatten_functional_groups(out, shared_fgs)
        flatten_functional_groups(out, per_frame_fgs)

        convert_frame_type_to_image_type(out)

        new_sop_uid = generate_uid()
        out.SOPClassUID = MRImageStorage
        out.SOPInstanceUID = new_sop_uid
        out.SeriesInstanceUID = new_series_uid
        out.InstanceNumber = frame_no

        if hasattr(out, "SeriesDescription") and out.SeriesDescription:
            out.SeriesDescription = "{0} [split]".format(out.SeriesDescription)
        else:
            out.SeriesDescription = "Split Enhanced MR"

        set_required_pixel_tags_from_array(out, frame)
        validate_required_geometry(out, frame_no)

        out.is_little_endian = True
        out.is_implicit_VR = False

        out.file_meta.TransferSyntaxUID = ExplicitVRLittleEndian
        out.file_meta.MediaStorageSOPClassUID = MRImageStorage
        out.file_meta.MediaStorageSOPInstanceUID = new_sop_uid
        out.file_meta.ImplementationClassUID = PYDICOM_IMPLEMENTATION_UID

        outfile = out_dir / "IM_{0:04d}.dcm".format(frame_no)
        dcmwrite(
            str(outfile),
            out,
            write_like_original=False
        )

        print("  written: {0}".format(outfile.name))

    print("Done.")


if __name__ == "__main__":
    main()
