# Changelog

Newest first. This is a user-facing summary, not a full engineering log.

## v0.4.1 (2026-09-24)

**New features**
- Subscriptions card (Tools screen): Pull Subscriptions lists every
  GreenLake subscription in the selected account's workspace - key,
  category (e.g. Advanced AP, Foundation Switch), type, available/total
  (e.g. 5/10), end date, and an Eval flag. Expired and fully used
  subscriptions are hidden unless you tick Show expired / Show fully
  used. Category and Type columns have filter dropdowns (Type narrows
  to the chosen Category).
- Set Hostname can target **Classic Central** instead of New Central
  (checkbox on the card), for customers still configuring in Classic.
  APs use Classic's AP settings, switches the `_sys_hostname` variable,
  gateways a device-level `hostname` command. UI groups only - devices
  in template groups are refused without changes. Tested live on a
  real AP, AOS-CX switch and 9004 gateway.

**Changed**
- The Onboard screen is now called **Onboard Devices**.

## v0.4.0 (2026-09-24)

**New features**
- Multiple accounts. Credentials now live in `token.yaml` (same format
  as the aruba_central project's token.yaml), one block per customer,
  and an **Account** dropdown in the top bar (visible on every screen) picks which one every
  screen uses. Add/delete accounts on the Credentials screen.
- UXI application_id is now stored per account instead of once for the
  whole app.
- Set Hostname (Post Onboard screen): sets a device's hostname in New
  Central via its System Information profile - APs, switches and
  gateways. New Hostname column in the device list (and CSV import),
  plus a Hostname Set tracking column. Tested live on a real AP.

**Changed**
- The Assign Site screen is now **Post Onboard** (Assign Site, Set
  Hostname, Create New Site).
- Device lists from older versions are upgraded automatically (two
  columns inserted, existing data moved along with them).
- `credentials.json` is replaced by `token.yaml`. An existing
  credentials.json is imported automatically on first launch and left
  in place; delete it once the imported account tests OK.
- Wipe on a credentials card now clears only the selected account.

**Fixed**
- Check Status showed every switch and gateway as "not seen yet" in
  Classic Central, even when it was Up - it only asked Classic
  Central's AP endpoint. It now tries the AP, switch and gateway
  endpoints and shows which type answered.

## v0.3.1 (2026-09-17)

**New features**
- Windows packaging (PyInstaller, onedir) - first build that runs as a
  real native app on Windows. See `central_onboarder/gui/packaging/
  README_windows.md` for how to build and distribute it.

## v0.3.0 (2026-09-15)

**Changed**
- Every Manual card's "Pull from Device List" checkbox now actually
  runs the sheet-driven batch step (reading each row's own Target
  Group/Site/Subscription Key, skipping rows already marked done) when
  checked, instead of just copying serials into the identifier field -
  it's the same action as the old standalone "Run X" buttons. Merged
  "Pre-Provision (Classic Central group)"'s Run button and "Assign
  Site"'s Run button into their respective Manual cards; there's one
  card per action now, not two.

## v0.2.0 (2026-09-15)

**New features**
- UXI sensor support: Device Type now includes UXI, alongside AP/
  Switch/Gateway, in the same device list/CSV. Onboard assigns UXI rows
  their own service (the UXI application, not Central) - store its
  application_id on the new Credentials screen "UXI Application" card.
  UXI rows skip pre-provisioning and site assignment, since those are
  Central-only concepts.
- Onboard screen: merged Pre-Provision onto the same screen as Onboard.
  Run Onboard Batch now also runs pre-provisioning as its last step.
  Added manual cards for Add to GLCP, Remove Service, and Pre-Provision
  (an explicit list of serials/MACs against an explicit group).
- Check Status (Onboard screen): looks up a serial or MAC's full state
  in one go - GLCP presence, service, subscription (from GLCP/New
  Central) plus pre-provisioned group, site, and check-in status (from
  Classic Central). Replaces the old separate Check Group/Check Status
  buttons.
- Assign Site screen: added a Manual: Assign Site card (explicit
  serials, device type, site name) and moved Create New Central Site
  here from Tools, with a proper timezone dropdown (was a free-text
  field).
- Credentials screen's UXI Application card: "Look up from GLCP..."
  lists every service instance provisioned in the workspace (name +
  id) via GLCP's Service Catalog API - click one to fill Application ID
  instead of having to already have a UXI device assigned somewhere to
  read its id off of.

**Fixes**
- Classic Central's Gateway device type is `"GATEWAY"`, not
  `"CONTROLLER"` (confirmed by the user - the prior value was an
  unverified guess by analogy with older Aruba API terms).

## v0.1.0 (2026-09-15)

Initial scaffold.

**New features**
- Credentials screen: store and test New Central and Classic Central
  API clients.
- Device List screen: set a working device-list file, import a CSV, or
  add/edit devices manually.
- Onboard screen: add devices to GLCP, assign a GreenLake subscription,
  assign the Central service.
- Pre-Provision screen: assign devices to a Classic Central group.
- Assign Site screen: assign onboarded devices to a New Central site.
- Tools screen: create a New Central site.
