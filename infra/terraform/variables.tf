variable "project" {
  type    = string
  default = "consultrag"
}

variable "region" {
  type    = string
  default = "ap-south-1"
}

variable "aws_profile" {
  type    = string
  default = "consultrag"
}

variable "allowed_cidrs" {
  description = "IP ranges allowed to reach the load balancer, e.g. [\"203.0.113.7/32\"]. Stays restricted until CloudFront and Google sign-in exist."
  type        = list(string)

  validation {
    condition     = length(var.allowed_cidrs) > 0 && !contains(var.allowed_cidrs, "0.0.0.0/0")
    error_message = "List at least one IP range, and don't open the API to the whole internet yet."
  }
}

variable "desired_count" {
  description = "API containers to run. Keep 0 until the image is pushed and migrations have run."
  type        = number
  default     = 0
}

variable "image_tag" {
  type    = string
  default = "latest"
}

variable "oauth_audience" {
  description = "Google OAuth client ID. Empty until Phase 4."
  type        = string
  default     = ""
}
