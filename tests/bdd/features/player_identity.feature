Feature: Player Registration and Authentication
  As a new player I want to register and authenticate
  so that my progress is tracked across sessions.

  Scenario: Register a new player
    Given a handle "BraveSoul" that is not taken
    When the visitor registers with that handle
    Then the response status is 201
    And a session token is returned
    And the response handle is "BraveSoul"

  Scenario: Reject duplicate handle
    Given a handle "TakenName" that is already registered
    When the visitor registers with that handle
    Then the response status is 409

  Scenario: Retrieve player profile
    Given a registered player with a valid session token
    When the player requests their profile
    Then the response status is 200
    And the response handle is "BddHero"
