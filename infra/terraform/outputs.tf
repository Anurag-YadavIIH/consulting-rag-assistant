output "ecr_repository_url" {
  value = aws_ecr_repository.api.repository_url
}

output "cloudfront_url" {
  description = "The app's single HTTPS URL (frontend and API). Add it to Google's authorized JavaScript origins."
  value       = "https://${aws_cloudfront_distribution.main.domain_name}"
}

output "cloudfront_distribution_id" {
  value = aws_cloudfront_distribution.main.id
}

output "frontend_bucket" {
  value = aws_s3_bucket.frontend.id
}

output "google_client_id" {
  description = "Public OAuth client ID; the frontend build uses the same value the API checks."
  value       = var.oauth_audience
}

output "api_health_url" {
  value = "https://${aws_cloudfront_distribution.main.domain_name}/health"
}

output "load_balancer_dns_name" {
  description = "For the post-deploy check that direct access is refused. Not a usable URL."
  value       = aws_lb.api.dns_name
}

output "cluster_name" {
  value = aws_ecs_cluster.main.name
}

output "task_definition" {
  value = aws_ecs_task_definition.api.family
}

output "public_subnet_ids" {
  value = aws_subnet.public[*].id
}

output "api_security_group_id" {
  value = aws_security_group.api.id
}
