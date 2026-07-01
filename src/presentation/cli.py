from pathlib import Path

from dotenv import load_dotenv

# Load .env before any module that reads os.environ (model instantiation happens on import).
load_dotenv(Path(__file__).resolve().parents[2] / ".env", override=True)

import argparse  # noqa: E402 — import after dotenv intentional
from datetime import datetime  # noqa: E402

from src.presentation.dependencies import get_analysis_service, get_logger  # noqa: E402


class CLI:
    def _parse_args(self) -> argparse.Namespace:
        parser = argparse.ArgumentParser(description="Deptha - AI MRI Analysis")
        parser.add_argument("--input",    required=True, type=Path,  help="DICOM folder or zip")
        parser.add_argument("--context",  required=True, type=str,   help="Patient clinical context")
        parser.add_argument("--language", type=str,      default="English", help="Output language (default: English)")
        parser.add_argument(
            "--question",
            type=str,
            default=None,
            help="Primary clinical question (optional — uses default if omitted)",
        )
        return parser.parse_args()

    def run(self) -> None:
        args   = self._parse_args()
        log    = get_logger()
        output = Path("data/output") / datetime.now().strftime("%Y-%m-%d_%H-%M-%S")

        log.info("CLI invoked", input=str(args.input), output=str(output), language=args.language)

        service = get_analysis_service()

        kwargs: dict = dict(
            input_path      = args.input,
            patient_context = args.context,
            output_language = args.language,
        )
        if args.question:
            kwargs["clinical_question"] = args.question

        report = service.run(**kwargs)
        report.save_to_dir(output)

        log.info(
            "Report saved",
            sections_dir=str(output / "sections"),
            summary_dir=str(output / "summary"),
        )
        print(f"\nReport saved to: {output.resolve()}")
        print(f"  sections/  — one subfolder per anatomical section")
        print(f"  summary/   — integrated synthesis report")


if __name__ == "__main__":
    CLI().run()
