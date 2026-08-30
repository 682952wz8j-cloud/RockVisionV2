# DJI GNSS / vertical-datum specification provenance

Status: local provenance record for Rule C v1.  
Official source URLs that were not present in the approved implementation input are **not invented** here.

Access / review date: 2026-08-30.  
Project interpretation: RockVision V2 Rule C — spec-governed reference-ellipsoid default.

`officialUrl = "reviewed source, URL to be frozen"` until a human supplies the exact reviewed official URL. Do not substitute a similar-looking DJI page.

---

## 1. MRK Ellh / default ellipsoid / CORS caveat

- **publisher:** DJI
- **sourceTitle:** DJI Enterprise GNSS / MRK height and default-ellipsoid specification (reviewed project design input)
- **officialUrl:** reviewed source, URL to be frozen
- **reviewDate:** 2026-08-30
- **productApplicability:** DJI surveying-image / Timestamp.MRK contract used by approved DJI families
- **projectInterpretation:** MRK `Ellh` is GNSS geodetic / ellipsoidal height. Default reference ellipsoid is WGS84. An external CORS / benchmark / RTK correction source may use another ellipsoid.
- **proves:** Ellh ≠ orthometric / geoid / MSL. Default ellipsoid = WGS84. RTK source can override the ellipsoid.
- **doesNotProve:** That any specific RockVision flight used WGS84. That missing text tokens prove WGS84. That Terra `EPSG:32650` is the capture ellipsoid.

---

## 2. Matrice 4 Series MRK contract

- **publisher:** DJI
- **sourceTitle:** DJI Matrice 4 Series MRK / photo-field contract (reviewed project design input)
- **officialUrl:** reviewed source, URL to be frozen
- **reviewDate:** 2026-08-30
- **productApplicability:** DJI Matrice 4 Series, including Matrice 4E (`ProductName` / `DroneModel` / EXIF `Model`)
- **projectInterpretation:** Matrice 4 image-log `.MRK` records ellipsoid height. Matrice 4E captures that machine-identify as this family may use the approved DJI default branch.
- **proves:** `MATRICE_4E_MRK_SPEC_APPLICABILITY = PASS` when family is proven from approved camera fields. MRK field 9 is ellipsoid height.
- **doesNotProve:** Per-flight WGS84 identity. A Rule C v1 mapping from `RtkFlag` / `RtkDiffAge` / MRK `Q` to a named RTK source.

---

## 3. Terra Default vertical semantics

- **publisher:** DJI
- **sourceTitle:** DJI Terra vertical / Default coordinate-system specification (reviewed project design input)
- **officialUrl:** reviewed source, URL to be frozen
- **reviewDate:** 2026-08-30
- **productApplicability:** DJI Terra reconstructions that record `output vertical coordinate`
- **projectInterpretation:** Terra `vertical = Default` means ellipsoidal height. With empty `override_vertical_cs` and no geoid conversion, Terra does not apply an orthometric/geoid conversion.
- **proves:** Default vertical mode is a Rule C default-branch guard, not capture-ellipsoid proof.
- **doesNotProve:** Capture GNSS reference ellipsoid. That output `EPSG:32650` is the capture ellipsoid.

---

## 4. Terra SRSOrigin / output-coordinate semantics

- **publisher:** DJI
- **sourceTitle:** DJI Terra output CRS / SRSOrigin specification (reviewed project design input)
- **officialUrl:** reviewed source, URL to be frozen
- **reviewDate:** 2026-08-30
- **productApplicability:** DJI Terra export `metadata.xml` / `model_report.json` / SDK output geo descriptor
- **projectInterpretation:** `<SRS>` and `output coordinate` name the reconstruction **output** CRS. `SRSOrigin` is the model origin in that output frame.
- **proves:** Output CRS and origin are Terra spatial-frame facts already selected by the Terra module.
- **doesNotProve:** Capture reference ellipsoid. Numerical Ellh / `ref_GPS.altitude` / SRSOrigin Z identity as datum identity.

---

## 5. Matrice 4 Network RTK fields

- **publisher:** DJI
- **sourceTitle:** DJI Matrice 4 Series Network RTK photo-field contract (reviewed project design input)
- **officialUrl:** reviewed source, URL to be frozen
- **reviewDate:** 2026-08-30
- **productApplicability:** DJI Matrice 4 Series photo metadata
- **projectInterpretation:** Approved Network RTK override fields are exactly `NTRIPHost`, `NTRIPPort`, `NTRIPMountPoint`. A populated field is Network RTK workflow evidence. It does not imply CGCS2000. It blocks the WGS84 default unless the network reference system is independently proven from an approved explicit reference-system field.
- **proves:** Closed-table override detection. `FIELD_NOT_PRESENT` ≠ `FIELD_PRESENT_EMPTY` ≠ `FIELD_PRESENT_POPULATED`.
- **doesNotProve:** That missing NTRIP attributes are empty strings. That `RtkDiffAge` is Network RTK.

---

## 6. Rule C v1 closed-table dependency

Approved policy remains Rule C. Rule A rejected. Rule B not selected.

Default `DEFAULT_WGS84_BY_APPROVED_DJI_SPEC` requires:

1. Approved capture family from `APPROVED_CAPTURE_FAMILY_FIELDS` only.
2. Valid MRK Ellh.
3. Terra vertical Default and no geoid conversion (consumed Terra evidence, not Terra re-selection).
4. No populated `APPROVED_NETWORK_RTK_OVERRIDE_FIELDS`.
5. No populated `APPROVED_EXPLICIT_REFERENCE_SYSTEM_FIELDS` naming a non-WGS84 system or a conflict.

Override detection is that closed table only. Recursive keyword search is forbidden.

That default state must never be renamed `PROVEN_WGS84`.
