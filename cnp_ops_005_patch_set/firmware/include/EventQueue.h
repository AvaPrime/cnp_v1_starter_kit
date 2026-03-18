#pragma once
#include <Arduino.h>
#include <vector>

struct QueuedMessage {
  String topic;
  String messageId;
  String payload;
  bool requiresAck = false;
  uint32_t enqueuedAtMs = 0;
  uint8_t retries = 0;
};

class EventQueue {
 public:
  explicit EventQueue(size_t capacity) : capacity_(capacity) {}
  bool enqueue(const QueuedMessage& msg);
  bool hasPending() const;
  bool peek(QueuedMessage& out) const;
  bool pop();
  bool markAcknowledged(const String& targetMessageId);
  size_t size() const { return queue_.size(); }

 private:
  size_t capacity_;
  std::vector<QueuedMessage> queue_;
};
