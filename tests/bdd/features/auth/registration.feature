Feature: Anonymous player registration
  S11 FR-11.10-12: anonymous identity provisioning without credentials

  Scenario: Registration returns an access and refresh token pair
    When the visitor calls the anonymous registration endpoint
    Then the response status is 201
    And the response contains an access token and a refresh token
    And the player identity is anonymous

  Scenario: Each registration creates a unique player identity
    When the visitor registers anonymously twice
    Then the two registrations have different player_ids

  Scenario: Registration response contains no password or credential data
    When the visitor calls the anonymous registration endpoint
    Then the response status is 201
    And no password or credential fields are present in the response
