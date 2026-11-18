N_YEARS = 50000
RETURN_PERIOD = 200
RANK = N_YEARS // RETURN_PERIOD  # 250 : rang de l'AEP/OEP 200 ans (sort(..., decreasing = T)[250] en R)

POOL_TAG = "pool_property"
CATFILE_PATTERN = r".csv"  # motif regex de list.files(pattern = ".csv") en R
NON_LOB_COLS = ("year", "eventid", "model_id", "modelid")

TOTAL_LABEL = "Total"
ALL_LABEL = "All"
XL_ENTITY = "XL"
NO_POOL_FILE = "NO POOL FILE"  # Checkpool d'un risque sans pool file (et valeur initiale)
NO_POOL = "No pool"            # Checkpool d'un run sans pool file (cas segments)

AEP = f"AEP{RETURN_PERIOD}"

# Précision des sommes et moyennes de R (sum, rowSums, mean), qui dépend de la machine :
#   True  : R sous Windows ou Mac Intel (accumulation en long double 80 bits)
#   False : R sur Mac Apple Silicon (accumulation en double 64 bits)
# Seuls les derniers chiffres significatifs (et les messages Checkpool) en dépendent.
R_LONG_DOUBLE = True
OEP = f"OEP{RETURN_PERIOD}"
