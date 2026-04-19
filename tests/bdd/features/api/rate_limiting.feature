Feature: Rate Limiting
  As an API operator
  I want to enforce per-player rate limits
  So that the service remains stable under load

  Scenario: Successful requests include rate-limit headers
    Given a registered player with a valid session token
    And the player has an active game
    And rate limiting is enabled
    When the player submits turn text "I look around"
    Then the response status is 202
    And the response includes a "X-RateLimit-Limit" header
    And the response includes a "X-RateLimit-Remaining" header
    And the response includes a "X-RateLimit-Reset" header

  Scenario: Exceeding the rate limit returns 429 with retry guidance
    Given a registered player with a valid session token
    And the player has an active game
    And rate limiting is enabled
    And the player has exceeded the turn rate limit
    When the player submits turn text "One more try"
    Then the response status is 429
    And the response error code is "rate_limited"
    And the response includes a "Retry-After" header
