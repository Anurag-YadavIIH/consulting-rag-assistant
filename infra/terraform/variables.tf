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

variable "debug_allowed_cidrs" {
  description = "Temporary direct access to the load balancer for debugging, e.g. [\"203.0.113.7/32\"]. Empty (the default) means only CloudFront can reach it. Remove the value again when you're done."
  type        = list(string)
  default     = []

  validation {
    condition = alltrue([
      for c in var.debug_allowed_cidrs :
      # try(): Terraform's && doesn't short-circuit, so the prefix parse
      # must not error on a value that isn't a CIDR at all.
      try(can(cidrhost(c, 0)) && !strcontains(c, ":") && tonumber(split("/", c)[1]) >= 24, false)
    ])
    error_message = "Each entry must be an IPv4 range of /24 or narrower (a single IP is /32). 0.0.0.0/0 and other wide ranges are refused."
  }

  validation {
    condition     = length(var.debug_allowed_cidrs) <= 4
    error_message = "List at most 4 ranges (a load balancer rule condition takes 5 values)."
  }
}

variable "debug_bypass_origin_check" {
  description = "With debug_allowed_cidrs set: false (default) only opens the security group, so a direct request reaches the listener and gets its 403 (a useful check); true also forwards requests from those IPs to the API without the CloudFront origin header."
  type        = bool
  default     = false
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
  description = "Google OAuth web client ID. Public, not a secret. The frontend build uses the same value (NEXT_PUBLIC_GOOGLE_CLIENT_ID)."
  type        = string
  default     = "778432443327-tfr98qv01htq229443g0kjnvlkp2md4h.apps.googleusercontent.com"
}

variable "initial_admin_emails" {
  description = "Emails that become a global admin the first time they sign in with a verified Google account (once per account). Personal data: set it in terraform.tfvars (gitignored), never in committed files."
  type        = list(string)
  default     = []
  sensitive   = true

  validation {
    condition     = alltrue([for e in var.initial_admin_emails : can(regex("^[^@\\s,]+@[A-Za-z0-9-]+(\\.[A-Za-z0-9-]+)+$", e))])
    error_message = "Each entry must be a single email address."
  }
}

variable "allowed_email_domains" {
  description = "Optional. When set, only these email domains may sign in, plus invited emails and initial_admin_emails."
  type        = list(string)
  default     = []

  validation {
    condition     = alltrue([for d in var.allowed_email_domains : can(regex("^[A-Za-z0-9-]+(\\.[A-Za-z0-9-]+)+$", d))])
    error_message = "Each entry must be a domain such as example.com (no @, no spaces)."
  }
}

variable "invitation_ttl_days" {
  description = "Days an invitation stays usable."
  type        = number
  default     = 14

  validation {
    condition     = var.invitation_ttl_days >= 1 && var.invitation_ttl_days <= 90
    error_message = "Between 1 and 90 days."
  }
}

variable "csp_enforce" {
  description = "false: send the Content-Security-Policy as Report-Only (violations are only reported in the browser console). true: enforce it. Switch only after the post-deploy checks show no reports during sign-in, upload and query."
  type        = bool
  default     = false
}

variable "api_origin_read_timeout" {
  description = "Seconds CloudFront waits for the API to respond. CloudFront does not retry POST after this, so it bounds how long an upload may take to process. 1-120 without a quota increase; the load balancer idle timeout is set above it."
  type        = number
  default     = 60

  validation {
    condition     = var.api_origin_read_timeout >= 1 && var.api_origin_read_timeout <= 120
    error_message = "Must be between 1 and 120 seconds (CloudFront's default quota)."
  }
}
