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

  backend "azurerm" {} # values in backend.hcl (shared Project 1 state account); az CLI locally, OIDC in CI (M8)
}

# Real Azure. Identity from `az login` (use_cli defaults to true); subscription pinned explicitly.
# No emulator settings here: in particular NEVER skip_import_check_on_create_... (Project 1 D10).
provider "azurerm" {
  subscription_id = var.subscription_id

  resource_provider_registrations = "none"
  resource_providers_to_register = [
    "Microsoft.Authorization",
    "Microsoft.CognitiveServices",
    "Microsoft.Communication",
    "Microsoft.DocumentDB",
    "Microsoft.EventGrid",
    "Microsoft.Insights",
    "Microsoft.ManagedIdentity",
    "Microsoft.OperationalInsights",
    "Microsoft.ServiceBus",
    "Microsoft.Storage",
    "Microsoft.Web",
  ]

  storage_use_azuread = true # Shared Key is disabled

  features {
    resource_group {
      prevent_deletion_if_contains_resources = true # destroy fails loudly if something was created outside Terraform
    }

    storage {
      # No queue_properties / static_website blocks, so azurerm needn't call the data plane
      # (it would need data roles for the deployer). Same setting as Project 1.
      data_plane_available = false
    }

    template_deployment {
      delete_nested_items_during_deletion = true # destroy removes the knowledge container (D17) and ACS (D20)
    }

    application_insights {
      disable_generated_rule = true # Azure's "Failure Anomalies" rule: disabled on create, deleted on destroy (D22)
    }

    cognitive_account {
      purge_soft_delete_on_destroy = true # a soft-deleted account keeps its name (and quota) for 48 h otherwise
    }
  }
}
