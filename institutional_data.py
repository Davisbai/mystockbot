"""Parse FinMind daily institutional flows without treating missing data as zero."""
import numpy as np
import pandas as pd


ALIASES = {
    'Foreign_Buy': {'Foreign_Investor', '外資', '外資及陸資(不含外資自營商)'},
    'Trust_Buy': {'Investment_Trust', '投信'},
}


def parse_institutional_flows(payload, dates):
    result = pd.DataFrame(index=dates)
    for column in ALIASES:
        result[column] = np.nan
    result['Chip_Data_Available'] = False
    result['Chip_Data_Status'] = 'unavailable'
    if not isinstance(payload, dict) or payload.get('msg') != 'success' or not payload.get('data'):
        return result
    frame = pd.DataFrame(payload['data'])
    if not {'date', 'name', 'buy', 'sell'}.issubset(frame.columns):
        result['Chip_Data_Status'] = 'invalid_schema'
        return result
    frame['date'] = pd.to_datetime(frame['date'], errors='coerce').dt.normalize()
    frame['name'] = frame['name'].astype(str).str.strip()
    for column in ('buy', 'sell'):
        frame[column] = pd.to_numeric(frame[column], errors='coerce').replace([np.inf, -np.inf], np.nan)
    valid = frame[['date', 'buy', 'sell']].notna().all(axis=1)
    valid &= (frame['buy'] >= 0) & (frame['sell'] >= 0)
    frame = frame.loc[valid].copy()
    frame['net'] = (frame['buy'] - frame['sell']) / 1000.0
    for column, names in ALIASES.items():
        selected = frame.loc[frame['name'].isin(names)]
        # English/Chinese are alternative representations of one category.
        # Reject duplicate category/date records rather than double-count them.
        duplicate_dates = selected.loc[selected['date'].duplicated(keep=False), 'date']
        selected = selected.loc[~selected['date'].isin(duplicate_dates)]
        series = selected.set_index('date')['net']
        result[column] = series.reindex(result.index)
    available = result[list(ALIASES)].notna()
    result.loc[available.any(axis=1), 'Chip_Data_Status'] = 'partial'
    result['Chip_Data_Available'] = available.all(axis=1)
    result.loc[result['Chip_Data_Available'], 'Chip_Data_Status'] = 'available'
    return result
