import csv
import json
import re
import tempfile
import zipfile
from datetime import date
from pathlib import Path
from urllib.request import urlretrieve

import geopandas as gpd
from shapely.geometry import shape, MultiPolygon

CATCHMENTS_URL = "https://www.healthgis.nhs.uk/assets/shared/GP_catchments_data.zip"
CSV_URL = "https://www.odsdatasearchandexport.nhs.uk/api/getReport?report=epraccur"
PUBLIC_DIR = Path(__file__).parent / "public"
OUTPUT_FILE = PUBLIC_DIR / "gp_catchments.fgb"
HTML_FILE = PUBLIC_DIR / "index.html"


def download_data(tmp_dir: Path):
    print("Downloading catchment data...")
    zip_path = tmp_dir / "catchments.zip"
    urlretrieve(CATCHMENTS_URL, zip_path)
    print("Extracting...")
    with zipfile.ZipFile(zip_path) as zf:
        zf.extractall(tmp_dir / "catchments")
    geojson_dir = tmp_dir / "catchments"
    # Handle case where zip contains a subfolder
    subdirs = [d for d in geojson_dir.iterdir() if d.is_dir()]
    if len(subdirs) == 1 and not list(geojson_dir.glob("*.geojson")):
        geojson_dir = subdirs[0]

    print("Downloading practice CSV...")
    csv_path = tmp_dir / "epraccur.csv"
    urlretrieve(CSV_URL, csv_path)

    return geojson_dir, csv_path


def load_practice_data(csv_path: Path):
    practices = {}
    with open(csv_path) as f:
        for row in csv.reader(f):
            code = row[0]
            status = row[12]
            if status == "INACTIVE":
                continue
            if row[25] != "RO76":
                continue
            practices[code] = {
                "name": row[1],
                "postcode": row[9],
                "phone": row[17],
            }
    return practices


def extract_multipolygon(geojson_path: Path) -> MultiPolygon:
    with open(geojson_path) as f:
        data = json.load(f)

    polygons = []
    for feature in data["features"]:
        geom = shape(feature["geometry"])
        if geom.geom_type == "Polygon":
            polygons.append(geom)
        elif geom.geom_type == "MultiPolygon":
            polygons.extend(geom.geoms)

    if len(polygons) == 1:
        return polygons[0]
    return MultiPolygon(polygons)


def main():
    OUTPUT_FILE.parent.mkdir(exist_ok=True)

    with tempfile.TemporaryDirectory() as tmp:
        tmp_dir = Path(tmp)
        geojson_dir, csv_path = download_data(tmp_dir)

        practices = load_practice_data(csv_path)
        print(f"Loaded {len(practices)} active practices from CSV")

        files = sorted(geojson_dir.glob("*.geojson"))
        print(f"Found {len(files)} geojson files")

        records = []
        skipped = 0
        for f in files:
            file_id = f.stem
            if file_id not in practices:
                skipped += 1
                continue
            info = practices[file_id]
            geom = extract_multipolygon(f)
            records.append({
                "id": file_id,
                "name": info["name"],
                "postcode": info["postcode"],
                "phone": info["phone"],
                "geometry": geom,
            })

        print(f"Skipped {skipped} inactive/unmatched practices")
        gdf = gpd.GeoDataFrame(records, geometry="geometry", crs="EPSG:4326")
        gdf.to_file(OUTPUT_FILE, driver="FlatGeobuf")
        print(f"Wrote {len(gdf)} features to {OUTPUT_FILE}")

    # Update date in HTML
    today = date.today().strftime("%-d %B %Y")
    html = HTML_FILE.read_text()
    html = re.sub(
        r'(<span id="data-date">)[^<]*(</span>)',
        rf"\g<1>{today}\g<2>",
        html,
    )
    HTML_FILE.write_text(html)
    print(f"Updated data date to {today}")


if __name__ == "__main__":
    main()
