import argparse
from datetime import datetime
from pathlib import Path

from dotenv import load_dotenv

from src.presentation.dependencies import get_analysis_service, get_logger

load_dotenv()


class CLI:
    def _parse_args(self) -> argparse.Namespace:
        parser = argparse.ArgumentParser(description="Deptha - AI MRI Analysis")
        parser.add_argument("--input",    required=True, type=Path, help="DICOM zip or directory")
        parser.add_argument("--context",  required=True, type=str,  help="Patient clinical context")
        parser.add_argument("--slices",   type=int,      default=5,  help="Slices per series (default: 5)")
        parser.add_argument("--language", type=str,      default="English", help="Output language (default: English)")
        return parser.parse_args()

    def run(self) -> None:
        args   = self._parse_args()
        log    = get_logger()
        output = Path("data/output") / datetime.now().strftime("%Y-%m-%d_%H-%M-%S")

        log.info("CLI invoked", input=str(args.input), output=str(output), language=args.language)

        service = get_analysis_service()
        report  = service.run(
            input_path=args.input,
            patient_context=args.context,
            slices_per_series=args.slices,
            output_language=args.language,
        )

        report.save_to_dir(output)
        log.info("Report saved", pdf=str(output / "report.pdf"))
