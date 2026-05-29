# Changelog

All notable changes to this project will be documented in this file.

## [2.1.0] - 2026-05-29

### Added
- **Desktop & UI Customization**: New dedicated tab for managing desktop environment aesthetics.
- **Mouse Cursor Support**: Unified manager for GTK/GNOME and KDE Plasma cursor themes.
- **Icon Theme Support**: Ability to change system icon themes for both GTK and Plasma.
- **KDE Plasma Support**: Specialized support for applying Plasma Global Themes and Splash Screens.
- **Smart Theme Redirection**: Automatically detects and redirects Plymouth animations miscategorized as desktop themes.
- **Expanded Archive Support**: Support for `.tar.xz`, `.tar.gz`, `.tar.bz2`, and `.zip` archives.
- **Manual KDE Note**: Information card for users on non-KDE environments.

### Fixed
- Fixed 404 error in update checker (corrected GitHub ID to `helllopratik`).
- Fixed "invalid file" error when installing themes from nested archives using recursive searching.
- Improved Pling/OpenDesktop search precision with category-specific filtering.
- Improved stability on non-KDE distributions by gracefully disabling Plasma-only features.

### Changed
- Updated application version to 2.1.0.
- Updated README with new features, correct version numbers, and optional dependencies.
- Updated maintainer info and repository links across the codebase.
