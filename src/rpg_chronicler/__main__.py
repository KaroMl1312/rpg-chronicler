from .storage.drive import sync_from_gdrive, upload_to_gdrive
from .summary import generate_summaries
from .transcription.runner import transcribe_new_files


def main():
    sync_from_gdrive()
    transcribe_new_files()
    generate_summaries()
    upload_to_gdrive()


if __name__ == "__main__":
    main()
