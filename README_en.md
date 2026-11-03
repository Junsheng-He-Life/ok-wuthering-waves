# OK-WW macOS beta

[中文](README.md) · [Installation and use (Chinese)](docs/beta-user-guide.md) · [Release notes](docs/release-0.1.0-beta.2.md)

Download **ok-ww-macos-beta-0.1.0-beta.2.zip** from the [release](https://github.com/Junsheng-He-Life/ok-wuthering-waves/releases/tag/v0.1.0-beta.2). The complete asset contains both matching projects; GitHub source archives do not.

Requires Apple Silicon, macOS 14+, Python 3.13 and Xcode Command Line Tools. Extract both projects together, run **安装与检查.command**, then **启动.command**. Installation creates a dedicated virtual environment and a Finder .app launcher. This is a source beta, not a signed/notarized standalone binary or bundled Python runtime.

The GUI uses dropdowns for stages and cultivation characters. It supports Boss/Tacet farming, a specified material domain, and current cultivation needs. Cultivation targets do not change the combat party. Read the actual party before starting.

Reward claims are OFF by default. No-claim mode forces all spending allowances to zero. Explicitly enable claims and set finite waveplate, reward-unit, reserve and solvent limits when needed. Double claims count as two units. Pause/resume, immediate stop and stop after the current fight are available. Pausing input does not pause enemies in the game.

On errors, preserve the installation and pending-consumption records. Select the failed run under **记录与问题报告**, export a redacted ZIP, and attach it manually to a [GitHub report](https://github.com/Junsheng-He-Life/ok-wuthering-waves/issues/new?template=macos-test.yml). Reports contain versions, dependencies, task results, exception information and redacted log tails. Screenshots, full logs and account configuration are excluded by default. Redact UID/account details before adding screenshots separately. Never delete guards to unlock spending or retry an uncertain claim.

Fixes include verified material entry, recovery from an unentered team menu, Mornye airborne target-HUD handling and repeated unconfirmed E requests. This repaired version has offline checks but no new live-game acceptance. Some Boss/weekly/regional/field routes remain unsupported; 1080p is the main previously tested geometry. Start with no spending.

Contains AI-assisted code. Upstream attribution and licensing: [UPSTREAM.md](UPSTREAM.md). Windows users should use [upstream releases](https://github.com/ok-oldking/ok-wuthering-waves/releases).
