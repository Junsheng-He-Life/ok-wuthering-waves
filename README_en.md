# OK-WW macOS beta

[中文](README.md) · [Installation and use (Chinese)](docs/beta-user-guide.md) · [Release notes](docs/release-0.1.0-beta.3.md)

Download **OK-WW-macOS-arm64-0.1.0-beta.3.zip** from the [release](https://github.com/Junsheng-He-Life/ok-wuthering-waves/releases/tag/v0.1.0-beta.3). Extract it, drag **OK-WW 鸣潮助手.app** to Applications, and open it.

Requires Apple Silicon and macOS 14+. The App includes Python 3.13, locked dependencies, OCR models and a precompiled native helper; no Python, Xcode, Terminal or Codex installation is needed. It is ad-hoc signed, without Apple Developer ID signing or notarization. If macOS blocks the first launch, verify the download and checksum, then use the system's Privacy & Security “Open Anyway” flow. Do not disable system-wide protection. Grant only the capture/accessibility permissions reported by the app's diagnostics.

User records stay under `~/Library/Application Support/OK-WW`, including pending spending records across App replacements. Existing source-install users must reconcile their old ledger before migration; do not initialize an existing account as new. A separate paired source ZIP remains available for developers and still requires Python 3.13 and command line tools.

The GUI uses dropdowns for stages and cultivation characters. Cultivation categories are shared across selected target characters; Echo-only is the default. The live character Sonata name is checked against the Tacet filter before entry. Cultivation targets do not change the combat party. Read the actual party before starting.

Reward claims are OFF by default. No-claim mode forces all spending allowances to zero. Explicitly enable claims and set finite waveplate, reward-unit, reserve and solvent limits when needed. Double claims count as two units. Pause/resume, immediate stop and stop after the current fight are available. Pausing input does not pause enemies in the game.

On errors, preserve the installation and pending-consumption records. Select the failed run under **记录与问题报告**, export a redacted ZIP, and attach it manually to a [GitHub report](https://github.com/Junsheng-He-Life/ok-wuthering-waves/issues/new?template=macos-test.yml). Reports contain versions, dependencies, task results, exception information and redacted log tails. Screenshots, full logs and account configuration are excluded by default. Redact UID/account details before adding screenshots separately. Never delete guards to unlock spending or retry an uncertain claim.

Fixes include conservative multi-frame healing verification when maximum HP changes and safe recorder error reporting. Bounded source-runtime tests cleared Xin's recommended Sonata stages using Xuanling/Phrolova/Suisui; the final win did not trigger emergency healing, so the changed-maximum branch remains offline-verified. The standalone App is checked offline without additional gameplay. Some Boss/weekly/regional/field routes remain unsupported; 1080p is the main tested geometry. Start with no spending.

Contains AI-assisted code. Upstream attribution and licensing: [UPSTREAM.md](UPSTREAM.md). Windows users should use [upstream releases](https://github.com/ok-oldking/ok-wuthering-waves/releases).
