import base64
import io

import numpy as np
import pydicom
from PIL import Image


class ImageEncoder:
    def encode_series(self, series: dict[str, list[pydicom.Dataset]]) -> dict[str, list[str]]:
        return {label: [self._to_base64_png(ds) for ds in slices] for label, slices in series.items()}

    def _to_base64_png(self, ds: pydicom.Dataset) -> str:
        arr = self._normalize(ds)
        img = Image.fromarray(arr, mode="L").convert("RGB") if arr.ndim == 2 else Image.fromarray(arr)
        buf = io.BytesIO()
        img.save(buf, format="PNG")
        return base64.b64encode(buf.getvalue()).decode("utf-8")

    def _normalize(self, ds: pydicom.Dataset) -> np.ndarray:
        arr = ds.pixel_array.astype(np.float32)

        slope = float(getattr(ds, "RescaleSlope", 1))
        intercept = float(getattr(ds, "RescaleIntercept", 0))
        arr = arr * slope + intercept

        wc = getattr(ds, "WindowCenter", None)
        ww = getattr(ds, "WindowWidth", None)

        if wc is not None and ww is not None:
            wc = float(wc[0]) if hasattr(wc, "__iter__") else float(wc)
            ww = float(ww[0]) if hasattr(ww, "__iter__") else float(ww)
            lo, hi = wc - ww / 2, wc + ww / 2
        else:
            lo, hi = arr.min(), arr.max()

        arr = np.clip(arr, lo, hi)
        arr = (arr - lo) / (hi - lo) * 255 if hi > lo else np.zeros_like(arr)
        return arr.astype(np.uint8)
