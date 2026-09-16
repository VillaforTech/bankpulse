package com.bankpulse.split;

import java.util.HashMap;
import java.util.Map;
import org.apache.kafka.clients.CommonClientConfigs;
import org.apache.kafka.clients.producer.ProducerConfig;
import org.apache.kafka.common.serialization.StringSerializer;
import org.springframework.beans.factory.annotation.Value;
import org.springframework.context.annotation.Bean;
import org.springframework.context.annotation.Configuration;
import org.springframework.kafka.core.DefaultKafkaProducerFactory;
import org.springframework.kafka.core.KafkaTemplate;
import org.springframework.kafka.core.ProducerFactory;

@Configuration
public class SocialSplitKafkaConfiguration {
  @Bean
  ProducerFactory<String, String> socialSplitProducerFactory(@Value("${KAFKA_BOOTSTRAP:}") String configuredBootstrap) {
    String bootstrap = configuredBootstrap == null || configuredBootstrap.isBlank() ? "localhost:9092" : configuredBootstrap.trim();
    Map<String, Object> properties = new HashMap<>();
    properties.put(CommonClientConfigs.BOOTSTRAP_SERVERS_CONFIG, bootstrap);
    properties.put(ProducerConfig.KEY_SERIALIZER_CLASS_CONFIG, StringSerializer.class);
    properties.put(ProducerConfig.VALUE_SERIALIZER_CLASS_CONFIG, StringSerializer.class);
    properties.put(ProducerConfig.ACKS_CONFIG, "all");
    properties.put(ProducerConfig.ENABLE_IDEMPOTENCE_CONFIG, true);
    properties.put(ProducerConfig.MAX_BLOCK_MS_CONFIG, 500);
    return new DefaultKafkaProducerFactory<>(properties);
  }

  @Bean
  KafkaTemplate<String, String> socialSplitKafkaTemplate(ProducerFactory<String, String> producerFactory) {
    return new KafkaTemplate<>(producerFactory);
  }
}