import os
import io
import pandas as pd
from datetime import datetime
from typing import List, Dict, Any

EXPORT_COLUMNS_MAPPING = {
    "asin": "ASIN",
    "brand_name": "Brand Name",
    "matched_seller": "Matching PL Seller",
    "reviews": "Reviews Count",
    "buybox_seller": "Buy Box Seller",
    "founder_name": "Founder / Decision Maker",
    "linkedin_url": "LinkedIn Profile URL",
    "decision_maker_role": "Role / Title",
    "pl_confidence": "PL Confidence",
    "seller_match_type": "Seller Match Type",
    "all_sellers_found": "All Sellers Found",
    "product_title": "Product Title",
    "price": "Price",
    "rating": "Rating",
    "product_url": "Amazon Product URL"
}

def records_to_dataframe(records: List[Dict[str, Any]]) -> pd.DataFrame:
    """Convert raw extraction records to clean formatted DataFrame."""
    if not records:
        return pd.DataFrame(columns=list(EXPORT_COLUMNS_MAPPING.values()))

    df = pd.DataFrame(records)
    # Rename columns to human-friendly headers
    rename_dict = {k: v for k, v in EXPORT_COLUMNS_MAPPING.items() if k in df.columns}
    df = df.rename(columns=rename_dict)
    
    # Reorder columns to place key columns first
    ordered_cols = [c for c in EXPORT_COLUMNS_MAPPING.values() if c in df.columns]
    remaining_cols = [c for c in df.columns if c not in ordered_cols]
    return df[ordered_cols + remaining_cols]

def export_to_csv_bytes(records: List[Dict[str, Any]]) -> bytes:
    """Generate CSV bytes for download."""
    df = records_to_dataframe(records)
    return df.to_csv(index=False, encoding='utf-8-sig').encode('utf-8-sig')

def export_to_excel_bytes(records: List[Dict[str, Any]]) -> bytes:
    """Generate styled Excel bytes for download."""
    df = records_to_dataframe(records)
    output = io.BytesIO()
    with pd.ExcelWriter(output, engine='openpyxl') as writer:
        df.to_excel(writer, index=False, sheet_name="Private Label Brands")
        
        # Auto-adjust column widths
        worksheet = writer.sheets["Private Label Brands"]
        for col in worksheet.columns:
            max_len = 0
            col_letter = col[0].column_letter
            for cell in col:
                val_str = str(cell.value or "")
                if len(val_str) > max_len:
                    max_len = min(len(val_str), 50)
            worksheet.column_dimensions[col_letter].width = max(max_len + 3, 12)

    return output.getvalue()

def save_export_file(records: List[Dict[str, Any]], export_dir: str = "exports", fmt: str = "csv") -> str:
    """Save export directly to disk and return file path."""
    os.makedirs(export_dir, exist_ok=True)
    timestamp = datetime.now().strftime("%Y%m%d_%H%M%S")
    filename = f"amazon_pl_brands_{timestamp}.{fmt}"
    file_path = os.path.join(export_dir, filename)

    if fmt.lower() == "xlsx":
        with open(file_path, "wb") as f:
            f.write(export_to_excel_bytes(records))
    else:
        with open(file_path, "wb") as f:
            f.write(export_to_csv_bytes(records))

    return file_path
