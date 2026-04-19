Feature: Full Turn Flow
  As a player
  I want to submit turns and get narrative responses
  So that I can progress through the game story

  Scenario: Submit a turn and receive a stream URL
    Given a registered player with a valid session token
    And the player has an active game
    When the player submits turn text "I look around the room"
    Then the response status is 202
    And the response body contains a stream URL

  Scenario: Submitting turn on an ended game returns conflict
    Given a registered player with a valid session token
    And the player has an ended game
    When the player submits turn text "I try to continue"
    Then the response status is 409

  Scenario: Submitting empty input returns validation error
    Given a registered player with a valid session token
    And the player has an active game
    When the player submits empty turn text
    Then the response status is 422
