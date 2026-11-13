# Azure OpenAI: one account, a chat deployment and an embedding deployment (D19).
# Entra ID only: local (key) auth off, so the app identity's Cognitive Services OpenAI User role is the only way in.
terraform {
  required_providers {
    azurerm = { source = "hashicorp/azurerm" }
  }
}

resource "azurerm_cognitive_account" "this" {
  #checkov:skip=CKV_AZURE_134:Public endpoint: the Flex app has no VNet integration in the lab (D15); Entra-only access
  #checkov:skip=CKV2_AZURE_22:CMK not used for a disposable lab account; Microsoft-managed keys
  #checkov:skip=CKV_AZURE_247:Outbound is restricted with an empty allowlist: stricter than the check, which wants at least one FQDN
  name                = var.name
  location            = var.location
  resource_group_name = var.resource_group_name
  kind                = "OpenAI"
  sku_name            = "S0"

  custom_subdomain_name = var.name # required for Entra ID tokens: https://<name>.openai.azure.com/

  local_auth_enabled                 = false # no API keys: managed identity / Entra only (D6)
  public_network_access_enabled      = true  # D15
  outbound_network_access_restricted = true  # the service itself may call nothing (no "on your data" sources)
  fqdns                              = []

  identity {
    type = "SystemAssigned"
  }

  tags = var.tags
}

# Deployments on one account are created one at a time (parallel writes answer 409).
resource "azurerm_cognitive_deployment" "embedding" {
  name                   = var.embedding.model # the deployment name is what the app sends as `model` (D9 embeddingModel)
  cognitive_account_id   = azurerm_cognitive_account.this.id
  version_upgrade_option = "OnceCurrentVersionExpired"
  rai_policy_name        = "Microsoft.DefaultV2"

  model {
    format  = "OpenAI"
    name    = var.embedding.model
    version = var.embedding.version
  }

  sku {
    name     = var.embedding.sku
    capacity = var.embedding.capacity # thousands of tokens per minute
  }
}

resource "azurerm_cognitive_deployment" "chat" {
  name                   = var.chat.model
  cognitive_account_id   = azurerm_cognitive_account.this.id
  version_upgrade_option = "OnceCurrentVersionExpired"
  rai_policy_name        = "Microsoft.DefaultV2"

  model {
    format  = "OpenAI"
    name    = var.chat.model
    version = var.chat.version
  }

  sku {
    name     = var.chat.sku
    capacity = var.chat.capacity
  }

  depends_on = [azurerm_cognitive_deployment.embedding]
}

resource "azurerm_monitor_diagnostic_setting" "account" {
  count                      = var.diagnostics_enabled ? 1 : 0
  name                       = "diag-to-law"
  target_resource_id         = azurerm_cognitive_account.this.id
  log_analytics_workspace_id = var.log_analytics_workspace_id

  enabled_log {
    category_group = "allLogs"
  }
}
