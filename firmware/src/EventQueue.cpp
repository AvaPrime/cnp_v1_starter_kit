#include "EventQueue.h"

bool EventQueue::enqueue(const QueuedMessage& msg) {
  if (queue_.size() >= capacity_) return false;
  queue_.push_back(msg);
  return true;
}

bool EventQueue::hasPending() const { return !queue_.empty(); }

bool EventQueue::peek(QueuedMessage& out) const {
  if (queue_.empty()) return false;
  out = queue_.front();
  return true;
}

bool EventQueue::pop() {
  if (queue_.empty()) return false;
  queue_.erase(queue_.begin());
  return true;
}

bool EventQueue::markAcknowledged(const String& targetMessageId) {
  for (auto it = queue_.begin(); it != queue_.end(); ++it) {
    if (it->messageId == targetMessageId) {
      queue_.erase(it);
      return true;
    }
  }
  return false;
}
