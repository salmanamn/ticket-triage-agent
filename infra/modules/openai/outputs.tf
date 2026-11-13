output "account_id" {
  value = azurerm_cognitive_account.this.id
}

# The v1 endpoint the openai SDK uses with an Entra token provider as api_key (D3).
output "base_url" {
  value = "https://${azurerm_cognitive_account.this.custom_subdomain_name}.openai.azure.com/openai/v1/"
}

output "chat_deployment" {
  value = azurerm_cognitive_deployment.chat.name
}

output "embedding_deployment" {
  value = azurerm_cognitive_deployment.embedding.name
}
