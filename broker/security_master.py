"""
Resolves a Nifty option contract (strike + CE/PE + expiry) to the Dhan
security_id needed to place an order for it. The option-chain response used
elsewhere in the pipeline (market/option_chain.py) carries OI/LTP/Greeks but
no security_id - Dhan only exposes that mapping via a separate scrip-master
CSV, so this module owns that lookup and its local caching.

Filter columns/values verified directly against a live download of the
Dhan detailed scrip master (2026-07-17): NIFTY index options are rows where
UNDERLYING_SYMBOL=="NIFTY", INSTRUMENT=="OPTIDX", SEGMENT=="D" (derivatives),
SM_EXPIRY_DATE matches config.EXPIRY's "YYYY-MM-DD" format exactly, and
STRIKE_PRICE/OPTION_TYPE identify the exact contract - that combination is
confirmed unique (e.g. strike 24250 CE -> exactly one row, security_id
57350, DISPLAY_NAME "NIFTY 21 JUL 24250 CALL", LOT_SIZE 65.0).
"""

import os
import time

import pandas as pd
from dhanhq import Security

import config


class ContractNotFoundError(Exception):
    pass


class AmbiguousContractError(Exception):
    pass


def _cache_is_fresh(path):
    if not os.path.exists(path):
        return False
    age_hours = (time.time() - os.path.getmtime(path)) / 3600
    return age_hours < config.SECURITY_MASTER_MAX_AGE_HOURS


def _load_security_master():
    """
    Returns the full scrip-master DataFrame, using the on-disk cache if it's
    still fresh. fetch_security_list() both writes the CSV to `filename` and
    returns the parsed DataFrame, so the cache file it writes doubles as the
    persisted copy - no separate save step needed.
    """

    path = config.SECURITY_MASTER_CACHE_PATH

    if _cache_is_fresh(path):
        return pd.read_csv(path, low_memory=False)

    os.makedirs(os.path.dirname(path), exist_ok=True)
    df = Security.fetch_security_list(mode="detailed", filename=path)

    if df is None:
        raise ConnectionError("Failed to download Dhan security master CSV")

    return df


def resolve_security_id(strike, option_type, expiry=None):
    """
    Returns (security_id, lot_size) for a single Nifty index option contract.
    Raises rather than guessing if the filter doesn't land on exactly one
    contract - this feeds directly into a real order's security_id, so an
    ambiguous or missing match must stop the order, not fall back to
    anything.
    """

    if option_type not in ("CE", "PE"):
        raise ValueError(f"option_type must be 'CE' or 'PE', got {option_type!r}")

    expiry = expiry or config.EXPIRY

    df = _load_security_master()

    matches = df[
        (df["UNDERLYING_SYMBOL"] == "NIFTY")
        & (df["INSTRUMENT"] == "OPTIDX")
        & (df["SEGMENT"] == "D")
        & (df["SM_EXPIRY_DATE"] == expiry)
        & (df["STRIKE_PRICE"] == float(strike))
        & (df["OPTION_TYPE"] == option_type)
    ]

    if len(matches) == 0:
        raise ContractNotFoundError(
            f"No NIFTY {option_type} contract found for strike={strike} expiry={expiry} "
            f"in the security master - check config.EXPIRY is current"
        )

    if len(matches) > 1:
        raise AmbiguousContractError(
            f"Multiple contracts matched strike={strike} option_type={option_type} "
            f"expiry={expiry}: {matches['SECURITY_ID'].tolist()}"
        )

    row = matches.iloc[0]

    return str(int(row["SECURITY_ID"])), int(row["LOT_SIZE"])
