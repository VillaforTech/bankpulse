package com.bankpulse.split;

import static org.junit.jupiter.api.Assertions.assertEquals;
import static org.junit.jupiter.api.Assertions.assertNotNull;
import com.fasterxml.jackson.databind.JsonNode;
import com.fasterxml.jackson.databind.ObjectMapper;
import java.math.BigDecimal;
import java.time.Instant;
import org.junit.jupiter.api.Test;
import org.springframework.beans.factory.annotation.Autowired;
import org.springframework.boot.test.autoconfigure.orm.jpa.DataJpaTest;
import org.springframework.boot.test.autoconfigure.orm.jpa.TestEntityManager;
import org.springframework.test.context.TestPropertySource;

@DataJpaTest
@TestPropertySource(properties = {
    "spring.datasource.url=jdbc:h2:mem:socialsplit;DB_CLOSE_DELAY=-1",
    "spring.datasource.driver-class-name=org.h2.Driver",
    "spring.jpa.hibernate.ddl-auto=create-drop"
})
class SocialSplitPersistenceContractTest {
  @Autowired TestEntityManager entityManager;
  @Autowired SocialSplitOutboxRepository outbox;
  private final ObjectMapper mapper = new ObjectMapper();

  @Test void persistedSessionAndOutboxEventCanBeReconstructed() throws Exception {
    SplitSession session = entityManager.persistFlushFind(new SplitSession("host", new BigDecimal("100"), "USD"));
    session.advanceVersion();
    Instant occurredAt = Instant.parse("2026-09-15T12:00:03Z");
    SocialSplitOutboxEvent event = new SocialSplitOutboxEvent("event-persisted", "SplitCompleted", session.getId(), session.getAggregateVersion(), occurredAt, "{\"sessionId\":\"" + session.getId() + "\",\"closedAt\":\"2026-09-15T12:00:03Z\"}");
    entityManager.persistAndFlush(event);

    SocialSplitOutboxEvent reloaded = outbox.findById("event-persisted").orElseThrow();
    JsonNode payload = mapper.readTree(reloaded.getPayload());
    assertNotNull(reloaded.getAggregateId());
    assertEquals(session.getId(), payload.get("sessionId").asText());
    assertEquals(reloaded.getAggregateId(), session.getId());
    assertEquals("2026-09-15T12:00:03Z", payload.get("closedAt").asText());
    assertEquals(occurredAt, reloaded.getOccurredAt());
  }
}