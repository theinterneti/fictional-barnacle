Feature: SSE Streaming
  As a player
  I want to receive real-time narrative events from the server
  So that I can experience the game turn results as they are generated

  Scenario: SSE stream connection opens successfully
    Given a registered player with a valid session token
    And the player has an active game
    When the player opens the SSE stream for their game
    Then the SSE stream returns status 200
    And the SSE response has content type text/event-stream

  Scenario: Reconnect with Last-Event-ID replays buffered events
    Given a registered player with a valid session token
    And the player has an active game
    And buffered SSE events exist for the game
    When the player reconnects with Last-Event-ID "1"
    Then the SSE stream returns status 200
    And the replayed events are returned in the stream

  Scenario: SSE stream for non-owned game is rejected
    Given a registered player with a valid session token
    When the player opens the SSE stream for a game they do not own
    Then the response status is 404
