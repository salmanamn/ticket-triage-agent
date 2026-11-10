terraform {
  required_version = ">= 1.9.0"

  required_providers {
    azurerm = {
      source  = "hashicorp/azurerm"
      version = "~> 4.81"
    }
    random = {
      source  = "hashicorp/random"
      version = "~> 3.7"
    }
  }
}

# floci-az 0.16.0 (docker compose --profile iac). Local state; the emulator is create/destroy only (D18).
provider "azurerm" {
  features {
    # floci-az can't tell us reliably whether a resource already exists (Project 1 D10).
    # Local emulator only; never on real Azure, where it would overwrite resources.
    skip_import_check_on_create_and_allow_overwriting_existing_resources = true

    resource_group {
      prevent_deletion_if_contains_resources = false
    }
  }

  environment   = "stack"          # custom cloud, not public Azure
  metadata_host = "localhost:4577" # floci-az serves the cloud endpoints here (TLS, scripts/trust-floci-cert.sh)

  use_cli         = false
  subscription_id = "00000000-0000-0000-0000-000000000001"
  tenant_id       = "00000000-0000-0000-0000-000000000002"
  client_id       = "00000000-0000-0000-0000-000000000003"
  client_secret   = "fake-secret" # the emulator doesn't validate credentials

  resource_provider_registrations = "none" # the emulator needs no registrations
  storage_use_azuread             = true   # Shared Key is disabled -> Entra tokens
}
