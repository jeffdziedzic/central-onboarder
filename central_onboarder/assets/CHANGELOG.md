# Changelog

Newest first. This is a user-facing summary, not a full engineering log.

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
