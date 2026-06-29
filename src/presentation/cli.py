import argparse
import logging
import sys
from datetime import datetime
from pathlib import Path

from dotenv import load_dotenv

from src.presentation.dependencies import get_analysis_service

load_dotenv()

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s [%(levelname)s] %(message)s",
    stream=sys.stdout,
)
log = logging.getLogger("deptha")


class CLI:
    def _parse_args(self) -> argparse.Namespace:
        parser = argparse.ArgumentParser(description="Deptha - AI MRI Analysis")
        parser.add_argument("--input", required=True, type=Path, help="DICOM zip or directory")
        parser.add_argument("--context", required=True, type=str, help="Patient clinical context")
        parser.add_argument("--slices", type=int, default=5, help="Slices per series (default: 5)")
        return parser.parse_args()

    def run(self) -> None:
        args = self._parse_args()

        output_dir = Path("data/output") / datetime.now().strftime("%Y-%m-%d_%H-%M-%S")

        log.info(f"Input: {args.input}")
        log.info(f"Output dir: {output_dir}")

        service = get_analysis_service()
        report = service.run(
            input_path=args.input,
            patient_context=args.context,
            slices_per_series=args.slices,
        )

        report.save_to_dir(output_dir)
        log.info(f"Report saved -> {output_dir}/report.md and {output_dir}/report.pdf")

        print("\n" + "=" * 60)
        print(report.analysis)
