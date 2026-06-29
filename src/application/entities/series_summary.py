from dataclasses import dataclass


@dataclass
class SeriesSummary:
    label: str
    slices_total: int
    slices_analysed: int
    modality: str
