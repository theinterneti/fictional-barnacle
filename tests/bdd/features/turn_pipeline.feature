Feature: Turn Processing Pipeline
  As a player I want to submit turns and receive narrative responses
  so that I can progress through my adventure.

  Background:
    Given a registered player with a valid session token
    And the player has an active game

  Scenario: Submit a turn and receive acceptance
    When the player submits turn text "look around"
    Then the turn is accepted with status 202

  Scenario: Accepted turn includes a stream URL for narrative
    When the player submits turn text "look around"
    Then the turn is accepted with status 202
    And the response includes a stream URL

  Scenario: Empty input is rejected by validation
    When the player submits empty turn text
    Then the response status is 422
