[CmdletBinding()]
param(
    [string]$Repository = ""
)

$ErrorActionPreference = "Stop"
$PSNativeCommandUseErrorActionPreference = $true

function Invoke-GhApiJson {
    param([Parameter(Mandatory)][string[]]$Arguments)
    $output = & gh @Arguments
    if ($LASTEXITCODE -ne 0) { throw "gh api failed." }
    $joined = $output -join [Environment]::NewLine
    if ([string]::IsNullOrWhiteSpace($joined)) { return $null }
    return $joined | ConvertFrom-Json
}

function Invoke-GhApiSilent {
    param([Parameter(Mandatory)][string[]]$Arguments)
    & gh @Arguments --silent
    if ($LASTEXITCODE -ne 0) { throw "gh api failed." }
}

& gh auth status | Out-Null
if ($LASTEXITCODE -ne 0) { throw "GitHub CLI is not authenticated. Run gh auth login first." }

if ([string]::IsNullOrWhiteSpace($Repository)) {
    $Repository = (& gh repo view --json nameWithOwner --jq ".nameWithOwner").Trim()
}
if ($Repository -notmatch "^[A-Za-z0-9_.-]+/[A-Za-z0-9_.-]+$") {
    throw "Repository must use owner/name form."
}

$repoInfo = Invoke-GhApiJson @("api", "-H", "X-GitHub-Api-Version: 2022-11-28", "repos/$Repository")
$defaultBranch = [string]$repoInfo.default_branch
if ([string]::IsNullOrWhiteSpace($defaultBranch)) { throw "Could not resolve the repository default branch." }

Write-Host "Configuring public-repository baseline for $Repository ..."

$repoSettings = @{
    description = "Windows tray app for low-latency, deterministic market-news alerts with TradingView News Flow and local unread history."
    has_issues = $true
    allow_merge_commit = $true
    allow_squash_merge = $true
    allow_rebase_merge = $true
    allow_auto_merge = $false
    delete_branch_on_merge = $true
    allow_update_branch = $false
    security_and_analysis = @{
        secret_scanning = @{ status = "enabled" }
        secret_scanning_push_protection = @{ status = "enabled" }
    }
}
$repoSettingsJson = $repoSettings | ConvertTo-Json -Depth 10 -Compress
$repoSettingsJson | & gh api -H "X-GitHub-Api-Version: 2022-11-28" -X PATCH "repos/$Repository" --input - | Out-Null
if ($LASTEXITCODE -ne 0) { throw "Failed to update repository settings." }

Invoke-GhApiSilent @("api", "-H", "X-GitHub-Api-Version: 2022-11-28", "-X", "PUT", "repos/$Repository/vulnerability-alerts")
Invoke-GhApiSilent @("api", "-H", "X-GitHub-Api-Version: 2022-11-28", "-X", "PUT", "repos/$Repository/automated-security-fixes")
if ($repoInfo.visibility -eq "public") {
    Invoke-GhApiSilent @("api", "-H", "X-GitHub-Api-Version: 2022-11-28", "-X", "PUT", "repos/$Repository/private-vulnerability-reporting")
}

$rulesetBody = @{
    name = "Protect default branch"
    target = "branch"
    enforcement = "active"
    bypass_actors = @()
    conditions = @{ ref_name = @{ include = @("~DEFAULT_BRANCH"); exclude = @() } }
    rules = @(
        @{ type = "deletion" },
        @{
            type = "pull_request"
            parameters = @{
                allowed_merge_methods = @("merge", "squash", "rebase")
                dismiss_stale_reviews_on_push = $false
                require_code_owner_review = $false
                require_last_push_approval = $false
                required_approving_review_count = 0
                required_review_thread_resolution = $false
            }
        },
        @{
            type = "required_status_checks"
            parameters = @{
                do_not_enforce_on_create = $false
                strict_required_status_checks_policy = $true
                required_status_checks = @(
                    @{ context = "test (3.12)"; integration_id = 15368 },
                    @{ context = "test (3.13)"; integration_id = 15368 },
                    @{ context = "security-gate"; integration_id = 15368 }
                )
            }
        },
        @{ type = "non_fast_forward" },
        @{
            type = "code_scanning"
            parameters = @{
                code_scanning_tools = @(
                    @{ tool = "CodeQL"; alerts_threshold = "errors"; security_alerts_threshold = "high_or_higher" }
                )
            }
        }
    )
}

$rulesets = @(Invoke-GhApiJson @("api", "-H", "X-GitHub-Api-Version: 2022-11-28", "repos/$Repository/rulesets?includes_parents=false&per_page=100"))
$existingRuleset = $rulesets | Where-Object { $_.name -eq "Protect default branch" } | Select-Object -First 1
$rulesetJson = $rulesetBody | ConvertTo-Json -Depth 20 -Compress
if ($null -eq $existingRuleset) {
    $rulesetJson | & gh api -H "X-GitHub-Api-Version: 2022-11-28" -X POST "repos/$Repository/rulesets" --input - | Out-Null
}
else {
    $rulesetJson | & gh api -H "X-GitHub-Api-Version: 2022-11-28" -X PUT "repos/$Repository/rulesets/$($existingRuleset.id)" --input - | Out-Null
}
if ($LASTEXITCODE -ne 0) { throw "Failed to create or update the default-branch ruleset." }

# Delete only branches proven to belong to a merged PR into the default branch.
$parts = $Repository -split "/", 2
$owner = $parts[0]
$branches = @(Invoke-GhApiJson @("api", "-H", "X-GitHub-Api-Version: 2022-11-28", "repos/$Repository/branches?per_page=100"))
$deleted = 0
$skipped = 0
foreach ($branch in $branches) {
    $branchName = [string]$branch.name
    if ($branchName -eq $defaultBranch -or [bool]$branch.protected) { continue }

    $headFilter = $owner + ":" + $branchName
    $openPulls = @(Invoke-GhApiJson @("api", "-H", "X-GitHub-Api-Version: 2022-11-28", "-X", "GET", "repos/$Repository/pulls", "-f", "state=open", "-f", "base=$defaultBranch", "-f", "head=$headFilter", "-f", "per_page=1"))
    if ($openPulls.Count -gt 0) {
        Write-Host "SKIP open PR: $branchName"
        $skipped++
        continue
    }

    $closedPulls = @(Invoke-GhApiJson @("api", "-H", "X-GitHub-Api-Version: 2022-11-28", "-X", "GET", "repos/$Repository/pulls", "-f", "state=closed", "-f", "base=$defaultBranch", "-f", "head=$headFilter", "-f", "per_page=100"))
    $merged = @($closedPulls | Where-Object { $null -ne $_.merged_at }).Count -gt 0
    if (-not $merged) {
        Write-Host "SKIP not proven merged: $branchName"
        $skipped++
        continue
    }

    $encodedBranch = [Uri]::EscapeDataString($branchName)
    Invoke-GhApiSilent @("api", "-H", "X-GitHub-Api-Version: 2022-11-28", "-X", "DELETE", "repos/$Repository/git/refs/heads/$encodedBranch")
    Write-Host "DELETED merged branch: $branchName"
    $deleted++
}

$verifiedRepo = Invoke-GhApiJson @("api", "-H", "X-GitHub-Api-Version: 2022-11-28", "repos/$Repository")
$verifiedRulesets = @(Invoke-GhApiJson @("api", "-H", "X-GitHub-Api-Version: 2022-11-28", "repos/$Repository/rulesets?includes_parents=false&per_page=100"))
$verifiedRuleset = $verifiedRulesets | Where-Object { $_.name -eq "Protect default branch" } | Select-Object -First 1
if (-not [bool]$verifiedRepo.delete_branch_on_merge) { throw "Verification failed: delete_branch_on_merge is not enabled." }
if ($null -eq $verifiedRuleset -or $verifiedRuleset.enforcement -ne "active") { throw "Verification failed: default-branch ruleset is not active." }

Write-Host ""
Write-Host "GitHub public-repository baseline applied."
Write-Host "Repository: $Repository"
Write-Host "Default branch: $defaultBranch"
Write-Host "Delete branch on merge: $($verifiedRepo.delete_branch_on_merge)"
Write-Host "Ruleset: $($verifiedRuleset.name) ($($verifiedRuleset.enforcement))"
Write-Host "Merged branches deleted: $deleted"
Write-Host "Branches intentionally skipped: $skipped"
