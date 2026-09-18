# Crescent v1 enclosure

An open desk stand for the **Waveshare ESP32-S3-Touch-AMOLED-1.75**, with a
removable screen ring, two button plungers, adjustable speaker posts, a battery
cradle, and a rear cable channel.

![Crescent enclosure front and rear](preview/Crescent-print-model-overview.png)

**Start with the [print and assembly walkthrough](PRINT_AND_ASSEMBLY.md).**
It covers the fit kit, part quantities, M2/M3 fasteners, resin orientation,
display/buttons, speaker, battery, and cable routing.

| Folder | Use |
| --- | --- |
| [STL](STL) | 12 printable designs in millimetres, including optional parts and gauges |
| [M7-oriented](M7-oriented) | The same designs tilted for the Photon Mono M7; add supports and slice |
| [source](source) | Editable Python geometry generator, pinned requirements, and CAD checks |
| [assembly-reference](assembly-reference) | Assembly-coordinate geometry for inspection, not extra print parts |
| [preview](preview) | Renders of the exported geometry; electronics are reference objects |

Print **09 × 1, 02 × 1, 03 × 2, and 04 × 2** first. This fit kit uses about
9.66 mL of model volume before supports. The full standard assembly uses about
42.08 mL, before supports, optional spacers, and test pieces. Import from either
`STL` or `M7-oriented`, at 100% scale, not both.

The design targets a salvaged Google Home Mini speaker module in its original
acoustic housing and a CS-MSX200SL-size battery. Speaker mounting geometry is
adjustable and remains provisional. The battery cradle is a mechanical holder;
it does **not** establish electrical compatibility with the board. Verify voltage,
polarity, protection, connector, and charging requirements separately before wiring.

The supplied meshes passed the original digital solid/clearance checks recorded
in [verification.json](verification.json). **Physical print fit, resin strength,
switch action, stability, and acoustics remain unverified.** No pre-supported
or sliced printer job is supplied. Fit the small kit before committing to a stand.

Original enclosure geometry and source are GPL-3.0-or-later under the repository
[license](../../LICENSE). The vendor board STEP is not redistributed; see
[source instructions](source/README.md) for obtaining it. Public package files
are listed in `SHA256SUMS.json`; those hashes describe this sanitized distribution.
