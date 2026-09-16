package com.bankpulse.split;

import static org.junit.jupiter.api.Assertions.assertThrows;
import static org.mockito.Mockito.mock;
import static org.mockito.Mockito.verify;
import static org.mockito.Mockito.when;
import com.fasterxml.jackson.databind.ObjectMapper;
import java.math.BigDecimal;
import org.junit.jupiter.api.Test;

class SocialSplitServiceTest {
  @Test void rejectedCloseDoesNotCreateAnOutboxEvent() {
    SplitSessionRepository sessions = mock(SplitSessionRepository.class);
    SocialSplitOutboxRepository outbox = mock(SocialSplitOutboxRepository.class);
    SplitSession session = new SplitSession("host", new BigDecimal("100"), "USD");
    session.addParticipant("member", new BigDecimal("90"));
    when(sessions.findById("split-1")).thenReturn(java.util.Optional.of(session));
    SocialSplitService service = new SocialSplitService(sessions, outbox, new ObjectMapper());

    assertThrows(DomainViolationException.class, () -> service.close("split-1"));
    verify(outbox, org.mockito.Mockito.never()).save(org.mockito.ArgumentMatchers.any());
  }

  @Test void createCommitsOnlyStateAndOutboxWithoutRequestThreadPublishing() {
    SplitSessionRepository sessions = mock(SplitSessionRepository.class);
    SocialSplitOutboxRepository outbox = mock(SocialSplitOutboxRepository.class);
    SplitSession persisted = mock(SplitSession.class);
    when(persisted.getId()).thenReturn("split-1");
    when(persisted.getCreatedAt()).thenReturn(java.time.Instant.now());
    when(persisted.getTotalAmount()).thenReturn(new BigDecimal("100"));
    when(persisted.getCurrency()).thenReturn("USD");
    when(sessions.saveAndFlush(org.mockito.ArgumentMatchers.any())).thenReturn(persisted);
    SocialSplitService service = new SocialSplitService(sessions, outbox,
        new ObjectMapper().findAndRegisterModules());
    org.springframework.transaction.support.TransactionSynchronizationManager.initSynchronization();
    try {
      org.junit.jupiter.api.Assertions.assertSame(persisted,
          service.create("host", new BigDecimal("100"), "USD"));
      verify(outbox).save(org.mockito.ArgumentMatchers.any());
      org.junit.jupiter.api.Assertions.assertTrue(
          org.springframework.transaction.support.TransactionSynchronizationManager.getSynchronizations().isEmpty(),
          "HTTP transaction must not register synchronous after-commit publishing");
    } finally {
      org.springframework.transaction.support.TransactionSynchronizationManager.clearSynchronization();
    }
  }
}
