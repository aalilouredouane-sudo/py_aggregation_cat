import importlib.util
import subprocess
import sys
from pathlib import Path

# module importable -> spécification pip
REQUIREMENTS = {
    "numpy": "numpy>=1.24",
    "pandas": "pandas>=2.0",
    "openpyxl": "openpyxl>=3.1",
}


def ensure_dependencies() -> None:
    """Installe les packages manquants avant l'import du package aggregation_cat."""
    missing = [spec for mod, spec in REQUIREMENTS.items()
               if importlib.util.find_spec(mod) is None]
    if missing:
        subprocess.check_call([sys.executable, "-m", "pip", "install", *missing])


ensure_dependencies()

from aggregation_cat import AggregationCatPipeline  # noqa: E402

if __name__ == "__main__":
    AggregationCatPipeline(
        folder=Path("C:/Users/B497NP/OneDrive - AXA/Desktop/4. CAT Man-Made/FY26/4. reinsurance/3. final catfiles/20261020 - processed - split"),
        # entités à vérifier chaque année -> unité des catfiles
        units={"BEL": 1, "CHE": 1, "DEU": 1, "ESP": 1, "FRA": 1,
               "IRL": 1, "ITA": 1, "MEX": 1, "UK": 1, "XL": 1000},
        is_xl_pool_format=False,  # True si tous les périls XL sont déjà au format pool
        group=False,  # True : ajoute Gross_MM_reconciliation_Group.xlsx (somme des entités en euros)
        # taux de change vers l'euro par entité (utilisés seulement si group=True)
        fx_rates={"BEL": 1, "CHE": 1.05440742, "DEU": 1, "ESP": 1, "FRA": 1,  # Septembre 26
                  "IRL": 1, "ITA": 1, "MEX": 0.04893397, "UK": 1.16959064, "XL": 0.88039794},
        # Décembre 25 : CHE 1.07469103, MEX 0.04735734, UK 1.14527859, XL 0.85146239
    ).run()
