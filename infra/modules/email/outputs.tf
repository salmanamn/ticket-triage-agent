output "communication_service_id" {
  value = local.acs.id.value
}

output "endpoint" {
  value = "https://${local.acs.hostName.value}"
}

# Azure-managed domains send as DoNotReply@<guid>.azurecomm.net.
output "sender_address" {
  value = "DoNotReply@${azurerm_email_communication_service_domain.managed.from_sender_domain}"
}
