Feature: Auth session lifecycle
  S11 FR-11.20-23: token refresh, reuse detection, and logout

  Scenario: Valid refresh token rotation issues new credentials
    Given a player has registered anonymously and holds a refresh token
    When the player exchanges their refresh token
    Then the response status is 200
    And the response contains a new access token and refresh token

  Scenario: Reused refresh token triggers session revocation
    Given a player has an already-used refresh token
    When the player exchanges their refresh token
    Then the response status is 401
    And the error code is "SESSION_REVOKED"

  Scenario: Player logout succeeds and clears the session
    Given a player has a valid access token for logout
    When the player calls the logout endpoint
    Then the response status is 204

  Scenario: Refresh token is rejected as an access credential at logout
    Given a player presents a refresh token for logout
    When the player calls the logout endpoint
    Then the response status is 401
    And the error code is "AUTH_TOKEN_INVALID"
