import os
import re
import time
import subprocess
import ctypes
from pydicom import dcmread
from pydicom.uid import (
    ExplicitVRLittleEndian, ImplicitVRLittleEndian, DeflatedExplicitVRLittleEndian, ExplicitVRBigEndian
)
from pynetdicom import AE, evt
from pynetdicom.sop_class import (
    CTImageStorage, MRImageStorage, EnhancedMRImageStorage, EnhancedMRColorImageStorage,
    RTPlanStorage, RTStructureSetStorage, RTDoseStorage, PositronEmissionTomographyImageStorage,
    SpatialRegistrationStorage, DeformableSpatialRegistrationStorage,
    Verification
)
import concurrent.futures

# Configuration settings
AE_TITLE = "MRMULTI"
RECEIVE_PORT = 1333
SERVER_IP = "x.x.x.x"  # The IP address to bind the server to (LocalPC-IP)
DESTINATION_DIR = r"D:\Incoming"
INCOMING_DIR = os.path.join(DESTINATION_DIR, "incoming")
ERROR_DIR = os.path.join(DESTINATION_DIR, "errors")
EMF2SF_PATH = r"C:\dcm4che\bin"  # Path to emf2sf command

#Set window title
ctypes.windll.kernel32.SetConsoleTitleW("DICOM Receiver - MRMULTI")

# Liste der vertrauenswürdigen AE-Titel
TRUSTED_AE_TITLES = ['MRMULTI', 'TR_SEND', 'VARIAN', 'MYQASRS', 'RTPLANNING', 'TRUSTED_AE_2']

def is_trusted_ae(requestor_ae_title):
    """Überprüfe, ob der AE-Titel vertrauenswürdig ist."""
    return requestor_ae_title in TRUSTED_AE_TITLES

def handle_echo(event):
    """Handle incoming C-ECHO (Verification) requests."""
    requestor_ae_title = event.assoc.requestor.ae_title
    print(f"Verification request received from AE Title: {requestor_ae_title}")

    # Überprüfen, ob der AE-Titel in der Liste der vertrauenswürdigen Titel ist
    if not is_trusted_ae(requestor_ae_title):
        print(f"Untrusted AE Title: {requestor_ae_title}. Echo rejected.")
        return 0xC001  # Status code for rejection

    print(f"Trusted AE Title: {requestor_ae_title}. Echo accepted.")
    return 0x0000  # Success status for trusted AE-Titles

# Create directories if they don't exist
os.makedirs(DESTINATION_DIR, exist_ok=True)
os.makedirs(INCOMING_DIR, exist_ok=True)
os.makedirs(ERROR_DIR, exist_ok=True)

def get_incoming_dir_for_ae(ae_title):
    """Return the incoming directory based on the AE title of the requesting device."""
    ae_title_mapping = {
        # Füge hier weitere AE-Title spezifische Mappings hinzu
        'MYQASRS': r"D:\IncomingIBA",
        'zCTSCANNER': os.path.join(DESTINATION_DIR, "incoming_ctscanner"),
    }
    # Standard fallback zu 'incoming' Ordner, wenn AE-Titel nicht in der Mapping enthalten ist
    return ae_title_mapping.get(ae_title, os.path.join(DESTINATION_DIR, "incoming"))

def sanitize_folder_name(name):
    """Sanitize folder name to remove invalid characters."""
    return re.sub(r'[<>:"/\\|?*^]', '_', name)  # Replace invalid characters with underscores

def create_subfolder(ds, base_folder, modality, date):
    """Create a subfolder based on StudyID, SeriesID, SeriesDescription, and image count."""
    try:
        # Extract necessary metadata for folder naming
        study_id = getattr(ds, 'StudyID', None)
        series_id = getattr(ds, 'SeriesNumber', None)
        series_description = getattr(ds, 'SeriesDescription', 'NoDescription')
        image_count = getattr(ds, 'NumberOfFrames', 0)

        # Check if the necessary identifiers are available
        if not study_id or not series_id:
            raise ValueError("Missing StudyID or SeriesID for folder creation.")

        # Sanitize the SeriesDescription for safe file path usage
        series_description = sanitize_folder_name(series_description)

        # Create folder name
        if image_count == 0:
            folder_name = f"{date}_{study_id}_{series_id}_{series_description}"
        else:
            folder_name = f"{date}_{study_id}_{series_id}_{series_description}_{image_count}"
        folder_path = os.path.join(base_folder, modality, folder_name)
        os.makedirs(folder_path, exist_ok=True)
        return folder_path
    except Exception as e:
        print(f"Could not create subfolder: {str(e)}. Saving in base folder.")
        return base_folder

# Konstanter Executor für parallelisierte Aufgaben
executor = concurrent.futures.ThreadPoolExecutor(max_workers=4)  # Anpassen der Anzahl der Threads nach Bedarf

def handle_store(event):
    """Handle incoming DICOM C-STORE requests."""
    ds = event.dataset
    ds.file_meta = event.file_meta
    try:
        # Extract patient ID and modality, including differentiation for MR types
        requestor_ae_title = event.assoc.requestor.ae_title
        print(f"Request received from AE Title: {requestor_ae_title}")

        # Dynamically set incoming directory based on AE Title
        incoming_dir = get_incoming_dir_for_ae(requestor_ae_title)
        os.makedirs(incoming_dir, exist_ok=True)

        patient_id = sanitize_folder_name(getattr(ds, 'PatientID', 'UNKNOWN_PATIENT'))
        patient_name_element = ds.get((0x0010, 0x0010), None)
        patient_name = sanitize_folder_name((str(patient_name_element.value) if patient_name_element else 'UNKNOWN_PATIENT'))
        modality = getattr(ds, 'Modality', 'UNKNOWN_MODALITY')

        # Check if modality is MR, CT, or PET to decide on folder creation
        needs_subfolder = modality in ['MR', 'CT', 'PT']  # PT is used for PET images

        # Extract date with priority: InstanceCreationDate -> ContentDate -> 'UNKNOWN_DATE'
        instance_creation_date = getattr(ds, 'InstanceCreationDate', None)
        content_date = getattr(ds, 'ContentDate', None)
        series_date = getattr(ds, 'SeriesDate', None)
        date_used = series_date or content_date or instance_creation_date or 'UNKNOWN_DATE'

        # Extract time with priority: InstanceCreationTime -> ContentTime -> '000000'
        instance_creation_time = getattr(ds, 'InstanceCreationTime', None)
        content_time = getattr(ds, 'ContentTime', None)
        series_time = getattr(ds, 'SeriesTime', None)
        acquisition_time = getattr(ds, 'AcquisitionTime', None)
        time_used = (series_time or acquisition_time or content_time or instance_creation_time or '000000').split('.')[0]  # Ignore milliseconds if present

        # Create a destination folder, with subfolders only for MR, CT, and PET
        if needs_subfolder:
            destination_folder = create_subfolder(ds, os.path.join(incoming_dir, patient_id+'_'+patient_name), modality, date_used)
        else:
            destination_folder = os.path.join(incoming_dir, patient_id+'_'+patient_name, modality)
            os.makedirs(destination_folder, exist_ok=True)
        
        # Create a unique filename based on SOPInstanceUID, date, and time
        filename = f"{modality}_{ds.SOPInstanceUID}_{date_used}{time_used}.dcm"
        file_path = os.path.join(destination_folder, filename)

        # Save the DICOM file (parallelized for enhanced MR)
        executor.submit(process_and_save_dicom, ds, file_path, modality, destination_folder)

    except Exception as e:
        # Handle errors by moving the file to the error folder
        error_filename = f"error_{event.request.AffectedSOPInstanceUID}.dcm"
        error_path = os.path.join(ERROR_DIR, error_filename)
        ds.save_as(error_path, write_like_original=False)
        print(f"Error processing file: {error_path} | Error: {str(e)}")

    return 0x0000  # Success status

def process_and_save_dicom(ds, file_path, modality, destination_folder):
    """Process and save DICOM file, including enhanced MR conversion."""
    try:
        # Save the DICOM file
        ds.save_as(file_path, write_like_original=False)
        print(f"Received and sorted DICOM file: {file_path}")

        # If the file is Enhanced MR, convert it to Standard MR using emf2sf and handle registrations
        if ds.SOPClassUID in [EnhancedMRImageStorage, EnhancedMRColorImageStorage]:
            try:
                # Convert Enhanced MR to Standard MR
                convert_enhanced_mr_to_standard(file_path, destination_folder)

                # Move converted Standard MR files to the appropriate StandardMR subfolder
                move_converted_files_to_standard_subfolder(file_path, ds)
                print(f"Converted Enhanced MR file and moved to Standard MR subfolder.")
                os.remove(file_path)
                print(f"Deleted original Enhanced MR file: {file_path}")

            except Exception as conv_error:
                print(f"Error converting Enhanced MR file: {file_path} | Error: {str(conv_error)}")

    except Exception as e:
        # Handle errors by moving the file to the error folder
        error_filename = f"error_{ds.SOPInstanceUID}.dcm"
        error_path = os.path.join(ERROR_DIR, error_filename)
        ds.save_as(error_path, write_like_original=False)
        print(f"Error processing file: {error_path} | Error: {str(e)}")



def convert_enhanced_mr_to_standard(input_path, output_dir):
    """Convert Enhanced MR DICOM to Standard MR using emf2sf."""
    try:
        # Define the output directory for the conversion
        output_path = os.path.join(output_dir, 'converted')
        os.makedirs(output_path, exist_ok=True)

        # Command to execute emf2sf conversion
        command = [
            os.path.join(EMF2SF_PATH, "emf2sf.bat"),
            "--out-dir", output_path,
            input_path
        ]

        # Run the conversion command
        result = subprocess.run(command, shell=True, check=True, capture_output=True, text=True)
        print(f"MR-Conversion successful: {result.stdout}")

    except subprocess.CalledProcessError as e:
        print(f"MR-Conversion failed: {e.stderr}")
        raise
    except Exception as e:
        print(f"An unexpected error occurred: {str(e)}")
        raise

def move_converted_files_to_standard_subfolder(original_file_path, ds):
    """Move converted Standard MR files to the appropriate StandardMR subfolder."""
    try:
        # Identify the correct StandardMR subfolder
        destination_folder = create_subfolder(ds, os.path.join(INCOMING_DIR, getattr(ds, 'PatientID', 'UNKNOWN_PATIENT')), "MR", getattr(ds, 'ContentDate', 'Date'))

        # Find all converted files in the 'converted' directory
        converted_dir = os.path.join(os.path.dirname(original_file_path), 'converted')
        for file_name in os.listdir(converted_dir):
            converted_file_path = os.path.join(converted_dir, file_name)
            new_file_path = os.path.join(destination_folder, file_name)

            # Move the converted file to the StandardMR subfolder
            os.replace(converted_file_path, new_file_path)
            print(f"Moved converted file to StandardMR subfolder: {new_file_path}")

        # Clean up the temporary converted directory
        os.rmdir(converted_dir)

    except Exception as e:
        print(f"Error moving converted files to StandardMR subfolder: {str(e)}")

def start_receiver(ae_title, ip, port):
    """Start the DICOM receiver service."""
    while True:
        try:
            ae = AE(ae_title=ae_title)

            # Add supported SOP classes and transfer syntaxes
            supported_sop_classes = [
                RTPlanStorage, RTStructureSetStorage, RTDoseStorage, CTImageStorage,
                MRImageStorage, EnhancedMRImageStorage, EnhancedMRColorImageStorage, PositronEmissionTomographyImageStorage,
                SpatialRegistrationStorage, DeformableSpatialRegistrationStorage,
                Verification
            ]
            transfer_syntaxes = [
                ExplicitVRLittleEndian, ImplicitVRLittleEndian, DeflatedExplicitVRLittleEndian, ExplicitVRBigEndian
            ]

            for sop_class in supported_sop_classes:
                ae.add_supported_context(sop_class, transfer_syntaxes)

            # Define event handlers for incoming DICOM files
            handlers = [(evt.EVT_C_STORE, handle_store)]

            # Start the server on the specified IP and port
            print(f"Starting DICOM receiver on IP {ip}, port {port} with AE Title '{ae_title}'...")
            ae.start_server((ip, port), evt_handlers=handlers)
        except Exception as e:
            #Print the Error and retry after 10secs
            print(f"Critical error in DICOM receiver: {str(e)}")
            print("Retrying in 10 seconds...")
            time.sleep(10)

if __name__ == "__main__":
    # Start the DICOM receiver with specified AE title, IP, and port
    start_receiver(AE_TITLE, SERVER_IP, RECEIVE_PORT)
