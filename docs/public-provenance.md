# Public content and screening

Every contribution must identify its source, author, license and permission to
redistribute in the review description. Original project code uses the root MIT
`LICENSE`. Review ownership and redistribution rights before adding source.
Do not imply that a third-party corpus is covered by the project's MIT license.
Retain dependency notices and the Wordle word-list source and MIT notice under
`dashboard/wordle/`. Content packs and private extensions require separate rights
review and do not inherit a public core license. Synthetic fixtures must be
independently authored, not paraphrased or transformed restricted source text.

Install the local hook with `git config core.hooksPath .githooks`. Supply the
private reference SHA-256 array via `WIDGETDECK_RESTRICTED_SHA256` or run
`python3 tools/screen_public.py --fingerprints /absolute/private/hashes.json
--require-fingerprints`. Never commit the array or corpus. Screening reads Git
blobs; staged checks inspect the index, including deletions and renames. It
reports paths and rule names, never matching values. Conflicts, symlinks and
submodules fail closed. The hook requires a configured nonempty fingerprint set.

The `Public screening / public-screen` CI job runs the same rules and requires
the repository secret `WIDGETDECK_RESTRICTED_SHA256`. Configure that secret and
make this job a required branch protection check before publishing. Fork PRs
without secret access fail closed; maintainers must review them in a trusted
branch without executing contributor code with private secrets. This workflow
does not configure hosted secrets or branch protection itself.

Checks cover recognizable secret formats, private credential references,
restricted exact bytes, runtime paths and generated artifacts. Existing legacy
deployment defaults and logical private-extension names remain supported; they
are not credentials. Exact hashes do not detect transformed/embedded content.
Review new assets and text manually, including provenance and licensing. A
passing tree check does not clear old Git objects, hosted refs, releases, caches
or registry images. Audit those independently before publication.

## Activate screening in each clone

Export the private reference hashes outside this repository. Configure the local
clone using its absolute fingerprint file path, then enable the versioned hook:

```sh
git config --local widgetdeck.screenFingerprints /private/location/hashes.json
git config --local core.hooksPath .githooks
```

The local Git configuration keeps that private path out of Git. The hook screens
the index and fails closed if required hashes are unavailable. The environment
variable remains supported when no local file is configured. Hooks are a local
guard and can be bypassed; hosted branch enforcement is independently required.

The Public screening workflow requires the repository Actions secret
`WIDGETDECK_RESTRICTED_SHA256` (the exported JSON array). Configure branch
protection/rulesets to require its `public-screen` status, a pull request, and
review before merging; prohibit force pushes/deletion and review administrator
bypass policy. Reconcile existing protections rather than replacing them blindly.
Run a trusted branch workflow after configuring the secret and verify both a
passing synthetic tree and rejection fixture before treating enforcement as live.
Fork pull requests without the secret deliberately fail closed; do not expose
private reference inputs through pull_request_target or an untrusted checkout.
Store only the hashes in the hosted secret, never the reference corpus. Workflow
files in a local commit do not prove hosted enforcement is configured.
