# DJI GNSS / vertical-datum specification provenance

Status: frozen local provenance record for Rule C v1.  
This is not a tutorial and does not copy large copyrighted passages.

Access / review date: 2026-08-30.  
Publisher of cited sources: DJI.  
Project interpretation is RockVision V2 Rule C — spec-governed reference-ellipsoid default.

---

## 1. MRK Ellh / default ellipsoid / CORS caveat

- **Source title:** DJI Enterprise Geospatial Solutions Advanced FAQ  
- **Publisher:** DJI  
- **Official URL:** https://enterprise-insights.dji.com/blog/geospatial-solutions-faq  
- **Relevant product family:** DJI Enterprise RTK imaging products (FAQ text covers Mavic 3 Enterprise, Matrice + P1/L1, and Terra; RockVision applies the MRK column contract to approved DJI surveying-image packages)  
- **Access / review date:** 2026-08-30  

**What the source proves (project interpretation):**

- Timestamp.MRK column 9 (`Ellh`) is GNSS geodetic / ellipsoidal height of the CMOS centre at exposure, not orthometric / EGM96 / EGM2008 / MSL height.
- The default reference ellipsoid for that height is WGS84.
- A different CORS / benchmark / RTK correction source may place the same Ellh field on another ellipsoid (the FAQ names CGCS2000 as an example).
- Image geotag coordinate system is not always geodetic WGS84; it depends on the NTRIP / RTK correction source.
- D-RTK 2 as the RTK source is documented as WGS84 (EPSG:4326) horizontal and ellipsoidal vertical.
- If Terra is not told otherwise, Terra defaults imported image coordinates to WGS84 (EPSG:4326) horizontal and ellipsoidal height. That Terra default is a processing assumption, not per-capture ellipsoid proof.

**What the source does not prove:**

- That a given RockVision incoming flight used WGS84.
- That absence of the string `CGCS2000` in files proves WGS84.
- That Terra output `EPSG:32650` is the capture GNSS ellipsoid.
- Meanings of `RtkFlag` / MRK `Q` / `RtkDiffAge` as named RTK-source enums for Rule C v1.

**Rule C dependency:** positive DJI contract + override detection (Network RTK / explicit non-WGS84) + documented WGS84 default. Not “string not found → WGS84”.

---

## 2. Matrice 4 Series MRK contract

- **Source title:** DJI Matrice 4 Series User Manual (English)  
- **Publisher:** DJI  
- **Official URL:** https://dl.djicdn.com/downloads/DJI_Matrice_4_Series/DJI_Matrice_4_Series_User_Manual_en.pdf  
- **Relevant product family:** DJI Matrice 4 Series (including Matrice 4E / 4T)  
- **Access / review date:** 2026-08-30  

**What the source proves (project interpretation):**

- Photo XMP / media-field contract includes `ProductName`, `DroneModel`, `GpsStatus`, `AltitudeType`, `RtkFlag`, `RtkDiffAge`, `SurveyingMode`, `SelfData`.
- Image log `.MRK` field 9 is **Ellipsoid height**.
- `MATRICE_4E_MRK_SPEC_APPLICABILITY = PASS` for captures machine-identified as Matrice 4 Series.

**What the source does not prove:**

- That Ellipsoid height is WGS84 for every Matrice 4 flight (the Enterprise FAQ CORS caveat still applies).
- A frozen mapping from `RtkFlag` / `RtkDiffAge` to `D_RTK2` vs `NETWORK_RTK` for Rule C v1. Those raw values may be recorded; they are not used as named-source inference.

**Rule C dependency:** approved capture family `DJI_MATRICE_4_SERIES` must be identified from generic asset metadata (`ProductName`, `DroneModel`, EXIF model). Wall ID is not a family identifier.

---

## 3. Matrice 4 Network RTK fields

- **Source title:** DJI Matrice 4 Series User Manual (English), photo-file field list  
- **Publisher:** DJI  
- **Official URL:** https://dl.djicdn.com/downloads/DJI_Matrice_4_Series/DJI_Matrice_4_Series_User_Manual_en.pdf  
- **Relevant product family:** DJI Matrice 4 Series  
- **Access / review date:** 2026-08-30  

Documented photo fields:

| Field | Manual meaning |
|---|---|
| `NTRIPMountPoint` | Mount point of Network RTK |
| `NTRIPPort` | Port of Network RTK |
| `NTRIPHost` | IP address or domain name of Network RTK |

Supporting Network RTK configuration semantics (host / port / mount point) also appear in DJI Payload SDK Network RTK docs:

- https://developer.dji.com/doc/payload-sdk-tutorial/en/function-overview/advanced-function/network-rtk.html  
- https://developer.dji.com/doc/payload-sdk-api-reference/en/advanced-function/network-rtk.html  

**What the source proves:**

- A populated approved Network RTK field is capture-side evidence of a Network RTK workflow.
- Rule C must distinguish field-not-present from field-present-empty from field-present-populated. Fields are not fabricated when the file format omits them.

**What the source does not prove:**

- That Network RTK implies CGCS2000.
- That Network RTK implies WGS84.
- That `RtkDiffAge > 0` is Network RTK.

**Rule C dependency:** populated `NTRIPHost` / `NTRIPPort` / `NTRIPMountPoint` sets `rtkSource = NETWORK_RTK` and **blocks** the WGS84 default unless the network reference system is independently proven.

---

## 4. Terra Default vertical semantics

- **Source title:** DJI Terra User Manual — Coordinate System (visible-light reconstruction)  
- **Publisher:** DJI  
- **Official URL:** https://terra.dji.com/user-manual/en/visible-light-reconstruction/coordinate-system.html  
- **Relevant product family:** DJI Terra  
- **Access / review date:** 2026-08-30  

**What the source proves (project interpretation):**

- Terra vertical setting `Default` means ellipsoidal height (not a named geoid / orthometric datum).
- Selecting a named vertical / geoid option is a different mode from Default.

Supporting paraphrase from DJI Terra operation guidance: for an elevation system that does not exist in the product list, choose Default (ellipsoidal height). Example: https://dl.djicdn.com/downloads/dji-terra/20241008/DJI%20Terra%20Operation%20Guide%20v4.2.pdf

**What the source does not prove:**

- Capture GNSS reference ellipsoid identity.
- That `EPSG:32650` or `output coordinate = WGS 84 / UTM zone 50N` is the capture ellipsoid.

**Rule C dependency:** `terraVerticalMode = DEFAULT` plus no configured geoid / `override_vertical_cs` is a **default-branch guard**, not ellipsoid proof by itself.

---

## 5. Terra SRSOrigin / output-coordinate semantics

- **Source title:** DJI Terra reconstruction metadata and output-coordinate documentation (manual above; reconstruction `metadata.xml` / `model_report.json` / SDK output geo descriptor as produced by Terra)  
- **Publisher:** DJI  
- **Official URLs:**  
  - https://terra.dji.com/user-manual/en/visible-light-reconstruction/coordinate-system.html  
  - https://enterprise-insights.dji.com/blog/geospatial-solutions-faq  
- **Access / review date:** 2026-08-30  

**What the source proves (project interpretation):**

- Terra `metadata.xml` `<SRS>` and `model_report.json` `output coordinate` name the **reconstruction output** CRS.
- `SRSOrigin` is the Terra model origin in that output frame.
- Empty `override_vertical_cs` with Default vertical means Terra did not apply a separate vertical CRS / geoid override.

**What the source does not prove:**

- Capture-side GNSS reference ellipsoid.
- Numerical identity of MRK Ellh, `sfm_geo_desc.ref_GPS.altitude`, and SRSOrigin Z as datum identity (`NUMERICAL_SANITY_IS_NOT_DATUM_PROVENANCE`).

**Rule C dependency:** output EPSG:32650 must never be copied into `referenceEllipsoid` or `PROVEN_WGS84`.

---

## 6. Rule C v1 dependency summary

Approved production policy: **Rule C — spec-governed default**.

| Rejected / not selected | Status |
|---|---|
| Rule A (negative-evidence-only WGS84) | REJECTED |
| Rule B (explicit evidence only for any AUTO_PASS including default) | SAFE_BUT_NOT_SELECTED_AS_PRODUCTION_POLICY |

Rule C may emit `DEFAULT_WGS84_BY_APPROVED_DJI_SPEC` only when:

1. Capture family is an approved DJI family covered by this frozen record (`DJI_MATRICE_4_SERIES`).
2. MRK Ellh is present and valid.
3. Terra vertical mode is Default and no geoid conversion is configured.
4. No Network RTK indicator is populated.
5. No external CORS / custom-benchmark / explicit non-WGS84 / conflicting reference-system evidence is present.

That state must never be renamed `PROVEN_WGS84`.
