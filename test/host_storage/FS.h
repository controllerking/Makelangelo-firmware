#pragma once
#include <stdint.h>
#include <stddef.h>
#include <algorithm>
#include <cstring>
#include <map>
#include <memory>
#include <string>
#include <vector>
class File {
  std::shared_ptr<std::vector<uint8_t>> data_;
  size_t offset_=0;
public:
  File()=default;
  explicit File(std::shared_ptr<std::vector<uint8_t>> data):data_(data){}
  explicit operator bool() const {return bool(data_);}
  size_t size() const {return data_ ? data_->size() : 0;}
  size_t available() const {return size()-offset_;}
  int read() {return available() ? (*data_)[offset_++] : -1;}
  size_t read(uint8_t *out,size_t n) {
    n=std::min(n,available());if(n)memcpy(out,data_->data()+offset_,n);offset_+=n;return n;
  }
  size_t readBytes(char *out,size_t n) {return read(reinterpret_cast<uint8_t*>(out),n);}
  size_t write(const uint8_t *in,size_t n) {
    if(!data_)return 0;
    if(offset_+n>data_->size())data_->resize(offset_+n);
    memcpy(data_->data()+offset_,in,n);offset_+=n;return n;
  }
  size_t write(uint8_t value) {return write(&value,1);}
  void flush() {}
  void close() {data_.reset();offset_=0;}
};
class FakeSPIFFS {
public:
  std::map<std::string,std::shared_ptr<std::vector<uint8_t>>> files;
  bool rejectRemoves=false,rejectRename=false;
  std::string rejectRenameTo;
  bool begin(bool) {return true;}
  bool exists(const char *path) {return files.count(path);}
  bool remove(const char *path) {return !rejectRemoves && files.erase(path);}
  bool rename(const char *from,const char *to) {
    if(rejectRename || rejectRenameTo==to || !exists(from))return false;
    files[to]=files[from];files.erase(from);return true;
  }
  File open(const char *path,const char *mode) {
    if(mode[0]=='w')files[path]=std::make_shared<std::vector<uint8_t>>();
    return exists(path) ? File(files[path]) : File();
  }
  size_t totalBytes() const {return 1408*1024;}
  size_t usedBytes() const {size_t n=0;for(const auto &entry:files)n+=entry.second->size();return n;}
};
extern FakeSPIFFS SPIFFS;
