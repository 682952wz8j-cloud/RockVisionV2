# DJI GNSS / vertical-datum specification provenance

Status: frozen local provenance record for Rule C v1.  
Review date: 2026-08-30.  
Publisher of all listed sources: DJI.

Each source is limited to the facts it actually supports. Do not enlarge one source onto another product or field.

Distinctions that remain mandatory:

- MRK Ellh semantic ≠ reference-ellipsoid identity
- Terra Default vertical ≠ per-capture WGS84 proof
- EPSG:32650 ≠ vertical CRS ≠ capture reference ellipsoid
- numerical agreement ≠ datum provenance
- GPSMapDatum ≠ PROVEN_WGS84
- Rule C `DEFAULT_WGS84_BY_APPROVED_DJI_SPEC` ≠ `PROVEN_WGS84`

---

## A. DJI Enterprise Geospatial Solutions Advanced FAQ

- **publisher:** DJI
- **sourceTitle:** DJI Enterprise Geospatial Solutions Advanced FAQ
- **officialUrl:** https://enterprise-insights.dji.com/blog/geospatial-solutions-faq
- **reviewDate:** 2026-08-30
- **productApplicability:** DJI Enterprise RTK imaging / Timestamp.MRK contract
- **projectInterpretation:** MRK column 9 (`Ellh`) is GNSS geodetic / ellipsoidal height. The documented default reference ellipsoid is WGS84. An external CORS / benchmark / RTK correction source may place the same field on another ellipsoid. D-RTK 2 is documented as WGS84 horizontal with ellipsoidal height.
- **proves:** Ellh ≠ orthometric / geoid / MSL. Default ellipsoid = WGS84. RTK source can override the ellipsoid.
- **doesNotProve:** That a given RockVision flight used WGS84. That Terra `EPSG:32650` is the capture ellipsoid. That `RtkFlag` / `RtkDiffAge` / MRK `Q` name a Rule C RTK source.

---

## B. DJI Matrice 4 Series User Manual

- **publisher:** DJI
- **sourceTitle:** DJI Matrice 4 Series User Manual (English)
- **officialUrl:** https://dl.djicdn.com/downloads/DJI_Matrice_4_Series/DJI_Matrice_4_Series_User_Manual_en.pdf
- **reviewDate:** 2026-08-30
- **productApplicability:** DJI Matrice 4E and Matrice 4T only (`M4E` / `M4T` / `DJI Matrice 4E` / `DJI Matrice 4T`)
- **projectInterpretation:** Image-log `.MRK` field 9 is ellipsoid height. Photo metadata includes `ProductName`, `DroneModel`, EXIF `Model`, and Network RTK fields `NTRIPHost`, `NTRIPPort`, `NTRIPMountPoint` when present.
- **proves:** Closed family allowlist for Rule C v1 is M4E/M4T only. MRK field 9 is ellipsoid height. Populated NTRIP fields are Network RTK workflow evidence.
- **doesNotProve:** Per-flight WGS84 identity. Applicability of M4D / M4TD / M4ET / other Matrice 4 products. That `RtkCoordinateSystem` or `RtkDatum` are real DJI capture-ellipsoid fields.

---

## C. DJI Terra Coordinate System manual

- **publisher:** DJI
- **sourceTitle:** DJI Terra User Manual — Coordinate System (visible-light reconstruction)
- **officialUrl:** https://terra.dji.com/user-manual/en/visible-light-reconstruction/coordinate-system.html
- **reviewDate:** 2026-08-30
- **productApplicability:** DJI Terra reconstructions
- **projectInterpretation:** Terra output / known-coordinate settings distinguish horizontal CRS from vertical mode.
- **proves:** Terra coordinate-system configuration is reconstruction output policy.
- **doesNotProve:** Capture GNSS reference ellipsoid. That output `EPSG:32650` is a vertical CRS or a capture ellipsoid.

---

## D. DJI Terra support — Image POS Data

- **publisher:** DJI
- **sourceTitle:** DJI Terra support — Image POS Data
- **officialUrl:** https://repair.dji.com/help/content?customId=01700005094&lang=en&paperDocType=ARTICLE&re=US&spaceId=17
- **reviewDate:** 2026-08-30
- **productApplicability:** DJI Terra image POS import
- **projectInterpretation:** Default POS altitude handling is ellipsoidal-height related when no other vertical conversion is selected.
- **proves:** Default / POS-altitude semantics used as a Rule C Terra-vertical guard input.
- **doesNotProve:** Per-capture WGS84 identity.

---

## E. DJI Terra support — Output Coordinate System Settings

- **publisher:** DJI
- **sourceTitle:** DJI Terra support — Output Coordinate System Settings
- **officialUrl:** https://repair.dji.com/help/content?customId=01700004937&lang=en&paperDocType=ARTICLE&re=US&spaceId=17
- **reviewDate:** 2026-08-30
- **productApplicability:** DJI Terra output coordinate settings
- **projectInterpretation:** `Default` vertical / POS altitude is ellipsoidal-height semantics, distinct from a named geoid or orthometric vertical system.
- **proves:** `terraVerticalMode = DEFAULT` and no configured geoid conversion are default-branch guards.
- **doesNotProve:** Capture reference ellipsoid. That Default output vertical is `PROVEN_WGS84`.

---

## F. DJI Terra API

- **publisher:** DJI
- **sourceTitle:** DJI Terra API / Terra Cloud algorithm geo descriptor
- **officialUrl:** https://developer.dji.com/doc/terra_api_tutorial/en/terra-cloud-algo.html
- **reviewDate:** 2026-08-30
- **productApplicability:** DJI Terra `geo_cs` / `override_vertical_cs` descriptor
- **projectInterpretation:** Horizontal `geo_cs` is separate from `override_vertical_cs`. A populated vertical override is independent of EPSG:32650.
- **proves:** `EPSG:32650` by itself does not prove vertical datum or capture ellipsoid. Empty `override_vertical_cs` is evidence that no separate vertical override was configured.
- **doesNotProve:** Capture GNSS reference ellipsoid identity.

---

## G. DJI Terra Output Format / SRSOrigin support

- **publisher:** DJI
- **sourceTitle:** DJI Terra support — Output Format / SRSOrigin
- **officialUrl:** https://repair.dji.com/help/content?customId=01700004767&lang=en&paperDocType=ARTICLE&re=US&spaceId=17
- **reviewDate:** 2026-08-30
- **productApplicability:** DJI Terra export `metadata.xml` SRS / SRSOrigin
- **projectInterpretation:** `SRSOrigin` is the output-model origin in the selected Terra output CRS.
- **proves:** SRSOrigin is Terra spatial-frame origin evidence consumed by existing Terra selection.
- **doesNotProve:** Capture reference ellipsoid. Numerical identity of MRK Ellh, `ref_GPS.altitude`, and SRSOrigin Z as datum identity.

---

## Rule C v1 dependency

Approved policy remains Rule C. Rule A rejected. Rule B not selected.

`DEFAULT_WGS84_BY_APPROVED_DJI_SPEC` requires all of:

1. Capture family is on the closed M4E/M4T allowlist.
2. MRK Ellh is present and valid.
3. Terra vertical is Default and no geoid conversion is configured.
4. No populated approved Network RTK field (`NTRIPHost` / `NTRIPPort` / `NTRIPMountPoint`).
5. No approved structured explicit alternate-reference evidence.
6. No conflicting authoritative reference evidence.

That state must never be renamed `PROVEN_WGS84`.

Real-file JPG/XMP fields `RtkCoordinateSystem` and `RtkDatum` are **not** approved capture-ellipsoid evidence.
