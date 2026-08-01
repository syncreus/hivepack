# Beekeep listings (staged)

Finalized registry listings for the community-squad pack, generated and
verified with `beekeep submit --listing`. Digests are pinned to the commit
named in each file's `source.commit`.

These are staged here because the ship-squad listings are still in review
(bartlomein/beekeep-registry#5). Once that PR resolves, copy these two files
into `agents/syncreus/` in a registry checkout, run the registry's
`node scripts/validate.mjs`, and open the PR.

If the pack changes before then, regenerate: re-run `beekeep submit
<snapshot> --listing <draft>` against the new commit so the sha256 and size
match what's on GitHub.
