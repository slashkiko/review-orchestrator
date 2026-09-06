# localization

Baseline: `fast`. Conditional.

Review whether the change stays translatable and stays correct outside the development locale.

Check user-visible strings introduced outside the translation mechanism, catalog keys added or removed on only one side, sentences assembled by concatenation or word order that translation cannot follow, plural and gender forms the shipped languages require, and locale-dependent formatting and parsing of numbers, currency, dates, times, time zones, collation, and name or address order. Include layout consequences the repository already handles, such as text expansion and right-to-left direction.

A finding cites the affected string or catalog entry and the locale in which it breaks. Use the locales the repository actually ships; do not require support for a language it does not.

Exclude wording and tone, translation quality itself, timestamp storage semantics owned by `data-integrity`, and interaction barriers owned by `accessibility`.
