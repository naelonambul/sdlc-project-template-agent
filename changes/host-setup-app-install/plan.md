# Implementation Plan

## Summary

An App is installed on selected repositories, so a repository created from the template is not covered until the owner adds it. Nothing tells the reader to do this. A live test on `sdlc-codex-solo-test` hit it: minting an installation token failed with HTTP 422, and the agent could not work under its identity. After the owner selected the repository in the installation settings, the same mint returned a token scoped to that repository only, and the settings page showed `Only select repositories` with it listed. This change adds the step to the host setup guide and the README Quick start.

## Files and components that change

<!-- Must be covered by change.json write_scope. -->

- `docs/host-setup.md`, "The agent's identity": a new paragraph after the permission list:

  ```text
  Add each new repository to the App's installation before an agent starts work: **Settings → Applications → Installed GitHub Apps → the App → Configure → Repository access → Only select repositories → Select repositories → Save**. Only the owner can do this, and creating a repository from the template does not do it. Until then, minting a token for that repository fails, for example with HTTP 422, and the agent cannot push under its identity. If the token helper has its own repository allowlist, add the repository there too. Mint one token to confirm before starting.
  ```

- `README.md`, Quick start step 3: name the step:

  ```text
  3. Configure the repository once, as `docs/host-setup.md` describes: add it to the GitHub App's installation, so the App account can open pull requests, your account reviews and merges them, and `main` is protected.
  ```

## Order of work

1. Edit both files. Proof: `grep -n "Repository access" docs/host-setup.md` and `grep -n "add it to the GitHub App" README.md` each print one line.
2. `python3 scripts/repo.py verify --change host-setup-app-install --full` passes, then close per `changes/README.md`.

## Tests and proof

The proof is the two greps and the control-plane tests. This changes documentation only.

## Risks and rollback

- The path comes from the live settings page of a personal account and from GitHub's documentation. GitHub may rename it. The paragraph also says what the step does, so it stays usable.
- Rollback: revert the squash commit.

## Out of scope

- Shipping a token helper in the template. It stays host-specific.
- A new release. This ships with the next one.
- `sdlc-codex-solo-test` itself.
