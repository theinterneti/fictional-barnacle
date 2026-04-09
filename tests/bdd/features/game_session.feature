Feature: Game Session Management
  As a player I want to create, list, and manage game sessions
  so that I can start and track my adventures.

  Background:
    Given a registered player with a valid session token

  Scenario: Create a new game session
    When the player creates a new game
    Then the response status is 201
    And the response contains a game ID
    And the game status is "created"

  Scenario: List games returns the player's sessions
    Given the player has an active game
    When the player lists their games
    Then the response status is 200
    And the response contains at least 1 game

  Scenario: Get a specific game by ID
    Given the player has an active game
    When the player requests that game by ID
    Then the response status is 200
    And the game status is "active"

  Scenario: End a game session
    Given the player has an active game
    When the player ends that game
    Then the response status is 200
    And the game status is "abandoned"

  Scenario: Cannot create game without authentication
    Given no authentication is provided
    When an unauthenticated player creates a game
    Then the response status is 401
