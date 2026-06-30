import base64
import io

import numpy as np
import pydicom
from PIL import Image


class ImageEncoder:
    def encode_series(
        self, series: dict[str, list[tuple[str, pydicom.Dataset]]]
    ) -> dict[str, dict[str, str]]:
        """Returns dict[series_label, dict[filename, base64_png]]."""
        return {
            label: {filename: self._to_base64_png(ds) for filename, ds in slices}
            for label, slices in series.items()
        }

    def _to_base64_png(self, ds: pydicom.Dataset) -> str:
        arr = self._normalize(ds)
        img = Image.fromarray(arr, mode="L").convert("RGB")
        buf = io.BytesIO()
        img.save(buf, format="PNG")
        return base64.b64encode(buf.getvalue()).decode("utf-8")

    def _normalize(self, ds: pydicom.Dataset) -> np.ndarray:
        arr = ds.pixel_array.astype(np.float32)

        slope = float(getattr(ds, "RescaleSlope", 1))
        intercept = float(getattr(ds, "RescaleIntercept", 0))
        arr = arr * slope + intercept

        # Percentile-based normalization — more robust than DICOM window/level for MRI
        lo = float(np.percentile(arr, 1))
        hi = float(np.percentile(arr, 99))

        arr = np.clip(arr, lo, hi)
        arr = (arr - lo) / (hi - lo) * 255 if hi > lo else np.zeros_like(arr)
        return arr.astype(np.uint8)
