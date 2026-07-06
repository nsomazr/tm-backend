# Administrative boundary GeoJSON (GADM format)

Place GeoJSON files here to import real admin polygons:

- `TZ_adm0.json` - country outline (admin level 0)
- `TZ_adm1.json` - regions (admin level 1)
- `TZ_adm2.json` - districts (admin level 2)

Repeat for `KE_*` and `UG_*` as needed.

## Download from GADM

1. Visit [https://gadm.org/download_country.html](https://gadm.org/download_country.html)
2. Select the country and download **GeoJSON** for levels 0, 1, and 2
3. Rename files to match the pattern above (e.g. `TZ_adm1.json`)
4. Run:

```bash
python manage.py import_admin_boundaries --country TZ
```

## Without GADM files

`seed_data` and `import_admin_boundaries` fall back to:

- **ADM0**: simplified Tanzania outline from `country_geo.py`
- **ADM1 (TZ only)**: approximate region boxes from `region_geo.py`

Upload official shapefiles via **Admin → Boundaries** to replace preset/GADM data.

## License

GADM data is for non-commercial use unless licensed from GADM. Replace with government shapefiles for production planning.
