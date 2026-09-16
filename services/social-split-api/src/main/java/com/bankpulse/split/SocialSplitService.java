package com.bankpulse.split;

import com.fasterxml.jackson.core.JsonProcessingException;
import com.fasterxml.jackson.databind.ObjectMapper;
import jakarta.transaction.Transactional;
import java.math.BigDecimal;
import java.time.Instant;
import java.util.Map;
import java.util.UUID;
import org.springframework.stereotype.Service;

@Service
public class SocialSplitService {
  private final SplitSessionRepository sessions; private final SocialSplitOutboxRepository outbox; private final ObjectMapper mapper;
  public SocialSplitService(SplitSessionRepository sessions,SocialSplitOutboxRepository outbox,ObjectMapper mapper){this.sessions=sessions;this.outbox=outbox;this.mapper=mapper;}
  @Transactional public SplitSession create(String hostMemberId,BigDecimal totalAmount,String currency){SplitSession session=sessions.saveAndFlush(new SplitSession(hostMemberId,totalAmount,currency));session.advanceVersion();outbox.save(event(session,"SplitCreated",Map.of("sessionId",session.getId(),"createdAt",session.getCreatedAt(),"totalAmount",session.getTotalAmount(),"currency",session.getCurrency())));return session;}
  @Transactional public SplitSession addParticipant(String id,String memberId,BigDecimal share){SplitSession session=get(id);session.addParticipant(memberId,share);session.advanceVersion();session=sessions.saveAndFlush(session);SplitParticipant p=session.getParticipants().get(session.getParticipants().size()-1);outbox.save(event(session,"ParticipantAdded",Map.of("sessionId",session.getId(),"participantId",p.getId(),"memberId",p.getMemberId(),"shareAmount",p.getShareAmount())));return session;}
  @Transactional public SplitSession authorize(String id,String participantId,String paymentReference){SplitSession session=get(id);session.authorize(participantId,paymentReference);session.advanceVersion();session=sessions.saveAndFlush(session);outbox.save(event(session,"ParticipantAuthorized",Map.of("sessionId",session.getId(),"participantId",participantId,"paymentReference","present")));return session;}
  @Transactional public SplitSession close(String id){SplitSession session=get(id);if(!session.closeIfAuthorized())return session;session.advanceVersion();session=sessions.saveAndFlush(session);Instant occurredAt=session.getClosedAt();outbox.save(event(session,"SplitCompleted",Map.of("sessionId",session.getId(),"closedAt",occurredAt),occurredAt));return session;}
  @Transactional public SplitSession get(String id){return sessions.findById(id).orElseThrow(()->new ResourceNotFoundException("split session not found"));}
  private SocialSplitOutboxEvent event(SplitSession session,String type,Map<String,Object> payload){return event(session,type,payload,Instant.now());}
  private SocialSplitOutboxEvent event(SplitSession session,String type,Map<String,Object> payload,Instant occurredAt){String eventId=UUID.randomUUID().toString();try{return new SocialSplitOutboxEvent(eventId,type,session.getId(),session.getAggregateVersion(),occurredAt,mapper.writeValueAsString(payload));}catch(JsonProcessingException ex){throw new IllegalStateException("cannot serialize social split event",ex);}}
}
